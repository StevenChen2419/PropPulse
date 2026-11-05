import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from app.models import Prop
from app.services.risk_intelligence_service import SOURCES, SPORTS, build_risk_intelligence


class RiskIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.props, self.logs = [], []
        self.db = MagicMock()
        def query(model):
            query = MagicMock()
            query.options.return_value = query
            query.filter.return_value = query
            query.order_by.return_value = query
            query.limit.return_value = query
            query.all.return_value = self.props if model is Prop else self.logs
            return query
        self.db.query.side_effect = query

    def player(self, sport, prop_type="points", stats=None):
        player = NS(id=sport, name=f"Player {sport}", team_abbr="TST", sport=sport)
        self.props.append(NS(id=sport, player_id=sport, player=player, is_active=True,
                             game_time=self.now + timedelta(days=1), odds_event_id="real-event", prop_type=prop_type))
        if stats is not None:
            self.logs.append(NS(player_id=sport, sport=sport, source=SOURCES[sport], external_game_id="game-1",
                                game_date=self.now - timedelta(days=2), stats=stats))
        return player

    def test_each_sport_uses_its_own_workload(self):
        fixtures = [("NBA", "points", {"minutes": 38}, "minutes", 38),
                    ("WNBA", "points", {"minutes": 32}, "minutes", 32),
                    ("MLB", "strikeouts", {"pitches": 100}, "pitches", 100),
                    ("NFL", "pass_yards", {"offensive_snaps": 68}, "snaps", 68),
                    ("NHL", "shots", {"time_on_ice": 24.5}, "minutes", 24.5)]
        for sport, market, stats, _, _ in fixtures:
            self.player(sport, market, stats)
        result = build_risk_intelligence(self.db)
        rows = {r["player"]["sport"]: r for r in result["players"]}
        for sport, _, _, unit, value in fixtures:
            with self.subTest(sport=sport):
                self.assertIsNotNone(rows[sport]["score"])
                self.assertTrue(0 <= rows[sport]["score"] <= 1)
                self.assertEqual(rows[sport]["workload"]["unit"], unit)
                self.assertEqual(rows[sport]["workload"]["value"], value)
                self.assertTrue(any("not a probability" in reason for reason in rows[sport]["reasons"]))

    def test_all_sports_visible_empty_and_filter_preserves_coverage(self):
        result = build_risk_intelligence(self.db)
        self.assertEqual([s["sport"] for s in result["sports"]], list(SPORTS))
        self.assertEqual(result["players"], [])
        self.player("NBA", stats={"minutes": 30})
        self.player("WNBA", stats={"minutes": 30})
        result = build_risk_intelligence(self.db, "NBA")
        self.assertEqual(len(result["sports"]), 5)
        self.assertEqual([r["player"]["sport"] for r in result["players"]], ["NBA"])

    def test_missing_workload_is_not_zero_or_low_risk(self):
        for sport in SPORTS:
            self.player(sport, "strikeouts" if sport == "MLB" else "points", {"points": 20})
        for row in build_risk_intelligence(self.db)["players"]:
            self.assertIsNone(row["score"])
            self.assertIsNone(row["workload"]["value"])
            self.assertTrue(row["missing_data"])
            self.assertEqual(row["label"], "Unknown")

    def test_no_history_is_unknown_not_zero_games(self):
        self.player("NBA")
        row = build_risk_intelligence(self.db)["players"][0]
        self.assertIsNone(row["score"])
        self.assertIsNone(row["games_in_7d"])

    def test_history_cutoffs_identity_source_and_deduplication(self):
        self.player("WNBA", stats={"minutes": 30})
        base = vars(self.logs[0])
        self.logs.extend([NS(**base), NS(**{**base, "external_game_id": "future", "game_date": self.now + timedelta(hours=1)}),
                          NS(**{**base, "external_game_id": "old", "game_date": self.now - timedelta(days=8)}),
                          NS(**{**base, "external_game_id": "bad", "source": "synthetic"}),
                          NS(**{**base, "external_game_id": "mock-1"}),
                          NS(**{**base, "external_game_id": "wrong", "sport": "NBA"})])
        self.props.append(NS(**vars(self.props[0])))
        result = build_risk_intelligence(self.db)
        self.assertEqual(len(result["players"]), 1)
        self.assertEqual(result["players"][0]["games_in_7d"], 1)
        self.assertEqual(result["players"][0]["workload"]["value"], 30)

    def test_only_real_active_upcoming_props(self):
        self.player("NBA", stats={"minutes": 30})
        prop = self.props[0]
        for field, value in [("is_active", False), ("odds_event_id", "mock-event"), ("odds_event_id", ""),
                             ("game_time", self.now - timedelta(days=1)), ("game_time", self.now + timedelta(days=8))]:
            old = getattr(prop, field)
            setattr(prop, field, value)
            with self.subTest(field=field, value=value):
                self.assertEqual(build_risk_intelligence(self.db)["players"], [])
            setattr(prop, field, old)

    def test_mlb_hitter_activity_and_today_date_only_exclusion(self):
        self.player("MLB", "hits", {"hits": 1})
        self.logs.append(NS(**{**vars(self.logs[0]), "external_game_id": "today", "game_date": self.now.replace(hour=0, minute=0, second=0, microsecond=0)}))
        row = build_risk_intelligence(self.db)["players"][0]
        self.assertEqual(row["method"], "experimental_hitter_activity")
        self.assertEqual(row["workload"]["value"], 1)
        self.assertTrue(any("proxy" in missing for missing in row["missing_data"]))

    def test_bad_numeric_workload_is_unknown(self):
        self.player("NBA", stats={"minutes": 30})
        for value in [None, "30", True, float("nan"), float("inf"), -1]:
            self.logs[0].stats["minutes"] = value
            self.assertIsNone(build_risk_intelligence(self.db)["players"][0]["score"])

    def test_nfl_role_activity_fallback_does_not_invent_snaps(self):
        player = self.player("NFL", "pass_yards", {"pass_attempts": 35})
        player.position = "QB"
        row = build_risk_intelligence(self.db)["players"][0]
        self.assertEqual(row["method"], "experimental_offensive_activity")
        self.assertEqual(row["workload"]["unit"], "attempts")
        self.assertEqual(row["workload"]["value"], 35)
        self.assertTrue(any("incomplete workload proxy" in value for value in row["missing_data"]))
        player.position = "RB"
        self.logs[0].stats = {"rush_attempts": 15, "receptions": 5}
        self.assertEqual(build_risk_intelligence(self.db)["players"][0]["workload"]["value"], 20)
        self.logs[0].stats = {"receptions": 5}
        row = build_risk_intelligence(self.db)["players"][0]
        self.assertEqual(row["workload"]["unit"], "receptions")
        self.assertEqual(row["workload"]["value"], 5)
        player.position = "CB"
        self.assertIsNone(build_risk_intelligence(self.db)["players"][0]["score"])

    def test_short_rest_increases_workload_index(self):
        self.player("NBA", stats={"minutes": 100})
        baseline = build_risk_intelligence(self.db)["players"][0]["score"]
        self.props[0].game_time = self.now + timedelta(hours=1)
        self.logs[0].game_date = self.now - timedelta(hours=1)
        row = build_risk_intelligence(self.db)["players"][0]
        self.assertAlmostEqual(row["score"], baseline + .15)
        self.assertTrue(any("Short calendar rest" in reason for reason in row["reasons"]))

    def test_two_way_baseball_history_is_filtered_by_role(self):
        self.player("MLB", "strikeouts", {"pitches": 95, "games_started": 1})
        self.logs.append(NS(**{**vars(self.logs[0]), "external_game_id": "batting", "stats": {"hits": 2, "plate_appearances": 4}}))
        row = build_risk_intelligence(self.db)["players"][0]
        self.assertEqual(row["workload"]["value"], 95)
        self.assertEqual(row["games_in_7d"], 1)
        self.props[0].prop_type = "hits"
        row = build_risk_intelligence(self.db)["players"][0]
        self.assertEqual(row["workload"]["value"], 1)
        self.assertFalse(any("Plate-appearance counts" in text for text in row["missing_data"]))


if __name__ == "__main__":
    unittest.main()
