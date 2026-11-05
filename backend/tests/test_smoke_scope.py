"""Scoped persistence regressions; isolated SQLite, no providers or application DB."""
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Event, Player, Prop, PropBook, PropBookSnapshot
from app.services.ingestion_control import RequestBudget
from scripts import fetch_odds as ingestion
from test_milestone2_ingestion import NBA, parsed, response, START


class SmokeScopeTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[m.__table__ for m in
            (Event, Player, Prop, PropBook, PropBookSnapshot)])
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.scope = {"event_id": "event-1", "prop_type": "points"}
        self.player = Player(name="Test Player", team="Home Team", team_abbr="HOM", sport="NBA")
        self.db.add(self.player)
        self.db.flush()
        self.quiet = patch("builtins.print")
        self.quiet.start()
        self.addCleanup(self.quiet.stop)

    def apply(self, rows):
        status = ingestion.make_sport_status(NBA)
        result = ingestion.apply_updates_for_sport(self.db, NBA, rows, status, scope=self.scope)
        self.db.commit()
        return result

    def test_unrelated_event_market_and_unbound_props_unchanged(self):
        others = [Prop(player_id=self.player.id, prop_type=kind, odds_event_id=event,
                       line=10.5, game_time=START, opponent="Home Team", is_active=True)
                  for event, kind in [("other", "points"), ("event-1", "rebounds"), (None, "points")]]
        self.db.add_all(others)
        self.db.commit()
        before = [(p.id, p.is_active, p.opponent, p.odds_event_id, p.line) for p in others]
        result = self.apply(parsed())
        # The unbound same-player/market row is unresolved; do not duplicate it.
        self.assertEqual(result["props_created"], 0)
        self.assertEqual(before, [(p.id, p.is_active, p.opponent, p.odds_event_id, p.line) for p in others])
        self.assertEqual(self.db.query(PropBook).count(), 0)
        self.assertEqual(self.db.query(Event).count(), 1)

    def test_repeat_and_older_observation_preserve_offer_history(self):
        self.apply(parsed())
        offer = self.db.query(PropBook).one()
        before = (offer.id, offer.line, offer.provider_observed_at, offer.ingested_at)
        self.assertEqual(self.apply(parsed())["sportsbook_snapshots_saved"], 0)
        rows = parsed(line=99.5)
        rows[0]["provider_observed_at"] = None
        self.assertEqual(self.apply(rows)["stale_observation_offers_skipped"], 1)
        self.assertEqual((offer.id, offer.line, offer.provider_observed_at), before[:3])
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)

    def test_empty_scope_keeps_activity_and_prices(self):
        self.apply(parsed())
        prop = self.db.query(Prop).one()
        prop.is_active = False
        self.db.commit()
        self.apply([])
        self.assertFalse(prop.is_active)
        self.assertEqual(self.db.query(PropBook).count(), 1)

    def test_scope_expansion_rejected_before_mutation(self):
        for field, value in [("event_id", "other"), ("prop_type", "rebounds"), ("sport_key", "icehockey_nhl")]:
            rows = parsed()
            rows[0][field] = value
            with self.assertRaises(ValueError):
                self.apply(rows)
        self.assertEqual(self.db.query(Prop).count(), 0)

    def test_unknown_or_wrong_team_players_skipped_without_creation(self):
        self.player.team = "Other Team"
        self.db.commit()
        result = self.apply(parsed() + parsed(name="Unknown Player"))
        self.assertEqual(result["players_created"], 0)
        self.assertEqual(result["unmatched_outcomes"], 2)
        self.assertEqual(self.db.query(Prop).count(), 0)

    def test_roster_changes_refused(self):
        with self.assertRaises(ValueError):
            ingestion.apply_updates_for_sport(self.db, NBA, parsed(), ingestion.make_sport_status(NBA),
                {"test player": {"team": "Other", "team_abbr": "OTH"}}, scope=self.scope)

    def test_retry_can_be_disabled_without_changing_default(self):
        client = MagicMock()
        client.get.return_value = response(503, {})
        budget = RequestBudget(2, 2, 0)
        with patch.object(ingestion, "ACTIVE_BUDGET", budget), patch.object(ingestion.time, "sleep") as sleep:
            status, _, _ = ingestion.get(client, "/test", {"markets": "player_points"}, max_attempts=1)
        self.assertEqual(status, 503)
        self.assertEqual(client.get.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
