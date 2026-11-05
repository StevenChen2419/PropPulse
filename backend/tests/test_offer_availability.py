import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from app.services.offer_service import offer_availability, odds_freshness
from app.services.slip_service import slip_selection
from app.services.parlay_service import estimate_parlay
from app.routers.props import best_line_fields, get_game_detail, get_ingestion_status
from app.routers.users import _prop_out, get_saved
from app.routers.players import serialize_line_movement, serialize_player_summary


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.offer = NS(sportsbook="FanDuel", line=10.5, over_odds=-110,
                        under_odds=120, provider_observed_at=self.now - timedelta(minutes=5))
        self.prop = NS(id="p", player_id="player", is_active=True,
                       sportsbook="FanDuel", line=10.5, over_odds=-110, under_odds=-110,
                       odds_event_id="provider-event", game_time=self.now + timedelta(hours=1),
                       book_offers=[self.offer], prop_type="points", line_24h_ago=None,
                       opponent="Away", is_home=True, popularity_count=0,
                       player=NS(id="player", name="Test", team="Home", team_abbr="H",
                                 sport="NBA", position=None, age=None))
        self.item = NS(prop_id="p", sportsbook="FanDuel", line=10.5, side="over")

    def decision(self, **kwargs):
        return offer_availability(self.prop, kwargs.get("sportsbook", "FanDuel"),
                                  kwargs.get("line", 10.5), kwargs.get("side", "over"), self.now)

    def test_fresh_and_recently_cached(self):
        self.assertEqual(self.decision()["availability"], "available")
        self.offer.provider_observed_at = self.now - timedelta(minutes=31)
        result = self.decision()
        self.assertFalse(result["actionable"])
        self.assertEqual(result["source"], "last_known")
        self.assertEqual(result["observation_age_seconds"], 1860)

    def test_expired_and_started(self):
        self.offer.provider_observed_at = self.now - timedelta(hours=6, microseconds=1)
        self.assertEqual(self.decision()["availability"], "expired")
        self.prop.game_time = self.now
        self.assertEqual(self.decision()["availability"], "game_started")
        self.assertIsNone(self.decision()["odds"])

    def test_invalid_prices(self):
        for odds in (None, True, 0, 99, -99, float("nan"), float("inf")):
            self.offer.over_odds = odds
            self.assertFalse(self.decision()["actionable"])

    def test_identity_missing_side_different_line_and_inactive(self):
        for book in (None, "Unknown", "Unsupported", "Demo"):
            self.assertFalse(self.decision(sportsbook=book)["actionable"])
        self.assertFalse(self.decision(line=11.5)["actionable"])
        self.offer.under_odds = None
        self.assertFalse(self.decision(side="under")["actionable"])
        self.prop.is_active = False
        self.assertFalse(self.decision()["actionable"])

    def test_no_legacy_price_or_synthetic_event(self):
        self.prop.odds_event_id = "synthetic-event"
        self.assertFalse(self.decision()["actionable"])
        self.prop.odds_event_id = "provider-event"
        self.prop.book_offers = []
        self.assertFalse(self.decision()["actionable"])

    def test_slip_becomes_unavailable_without_changing_identity(self):
        self.assertEqual(slip_selection(self.item, self.prop, self.now)["odds"], -110)
        self.offer.provider_observed_at = self.now - timedelta(hours=7)
        result = slip_selection(self.item, self.prop, self.now)
        self.assertEqual((result["sportsbook"], result["line"]), ("FanDuel", 10.5))
        self.assertEqual(result["availability"], "expired")
        self.assertIsNone(result["odds"])
        self.assertEqual(self.item.side, "over")

    def test_saved_expired_prop_is_returned_and_manageable(self):
        self.offer.provider_observed_at = self.now - timedelta(hours=7)
        db = MagicMock()
        saved_query, prop_query, fatigue_query = [MagicMock() for _ in range(3)]
        saved_query.filter.return_value.all.return_value = [NS(prop_id="p", side=None)]
        prop_query.join.return_value.options.return_value.filter.return_value.all.return_value = [self.prop]
        fatigue_query.filter.return_value.all.return_value = []
        db.query.side_effect = [saved_query, prop_query, fatigue_query]
        with patch('app.routers.users.load_game_logs', return_value={}):
            result = get_saved(NS(id="user"), db)["saved"]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["availability"], "expired")
        self.assertIsNone(result[0]["over_odds"])
        self.assertEqual(result[0]["sportsbook_offers"], [])
        db.delete.assert_not_called()
        db.commit.assert_not_called()

    def test_estimate_rejects_expired_offer_before_history_queries(self):
        self.offer.provider_observed_at = self.now - timedelta(hours=7)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [self.prop]
        result = estimate_parlay(db, [self.item, self.item])
        self.assertIsNone(result["decimal"])
        self.assertIsNone(result["independent_decimal"])
        self.assertEqual(result["availability"], "expired")
        self.assertEqual(db.query.call_count, 1)

    def test_mixed_offers_and_exact_line_best_prices(self):
        expired = NS(**{**vars(self.offer), "sportsbook": "DraftKings", "over_odds": 300,
                        "provider_observed_at": self.now - timedelta(hours=7)})
        other_line = NS(**{**vars(self.offer), "sportsbook": "BetMGM", "line": 11.5,
                           "over_odds": 250})
        self.prop.book_offers.extend([expired, other_line])
        result = best_line_fields(self.prop)
        self.assertEqual(result["best_over"]["odds"], -110)
        self.assertEqual(result["sportsbook_count"], 1)
        self.assertEqual(len(result["sportsbook_offers"]), 2)

    def test_utc_boundaries_and_response_time_age(self):
        self.offer.provider_observed_at = (self.now - timedelta(hours=6)).replace(tzinfo=None)
        self.assertFalse(self.decision()["actionable"])
        offset = timezone(timedelta(hours=-4))
        result = offer_availability(self.prop, "FanDuel", 10.5, "over", self.now.astimezone(offset))
        self.assertFalse(result["actionable"])
        later = self.now + timedelta(microseconds=1)
        self.assertFalse(offer_availability(self.prop, "FanDuel", 10.5, "over", later)["actionable"])
        self.offer.provider_observed_at = self.now + timedelta(microseconds=1)
        self.assertFalse(self.decision()["actionable"])
        self.offer.provider_observed_at = self.now - timedelta(minutes=30)
        self.assertEqual(self.decision()["source"], "live")
        self.assertEqual(odds_freshness(self.prop, self.now + timedelta(seconds=1))["source"], "last_known")

    def test_game_detail_source_contract_and_eligible_book_count(self):
        feed = {"props": [{"id": "p", "source": "last_known",
                           "sportsbook_offers": [{"sportsbook": "FanDuel"}]}],
                "total": 1, "refreshed_at": self.offer.provider_observed_at.isoformat()}
        context = {"game_key": "NBA|2026-10-14T12:00:00|Away|Home", "event_id": None,
                   "sport": "NBA", "game_time": "2026-10-14T12:00:00+00:00",
                   "away_team": "Away", "home_team": "Home", "identity_source": "legacy"}
        with patch("app.routers.props.get_feed", return_value=feed), \
                patch("app.routers.props.resolve_game", return_value=context):
            result = get_game_detail("NBA|2026-10-14T12:00:00|Away|Home", None, MagicMock())
        self.assertEqual(result["source"], "last_known")
        self.assertEqual(result["sportsbook_count"], 1)
        self.assertFalse(result["actionable"])

    def test_historical_ingestion_success_cannot_report_live(self):
        db = MagicMock()
        db.query.return_value.options.return_value.filter.return_value.all.return_value = [self.prop]
        self.offer.provider_observed_at = self.now - timedelta(hours=7)
        with patch("app.routers.props.read_ingestion_status", return_value={"source": "odds_api_props", "live_props_matched": 50}):
            result = get_ingestion_status(db)
        self.assertEqual(result["ingestion_source"], "odds_api_props")
        self.assertEqual(result["availability"], "unavailable")

    def test_ingestion_snapshots_do_not_establish_observed_price_movement(self):
        self.offer.provider_observed_at = self.now - timedelta(hours=7)
        self.prop.book_offers.append(NS(**{**vars(self.offer), "sportsbook": "DraftKings",
                                         "provider_observed_at": self.now}))
        snapshot = NS(line=9.5, over_odds=120, under_odds=-140, captured_at=self.now)
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = snapshot
        result = serialize_line_movement(db, self.prop)
        self.assertIsNone(result)  # Capture timestamps cannot prove observed movement.

    def test_unavailable_followed_player_remains_in_watchlist(self):
        with patch("app.routers.players.get_live_player_props", return_value=[]):
            result = serialize_player_summary(MagicMock(), self.prop.player, include_trends=True)
        self.assertEqual(result["id"], "player")
        self.assertEqual(result["live_prop_count"], 0)
        self.assertIsNone(result["top_prop"])



class ProviderObservationTests(unittest.TestCase):
    def test_ingestion_and_legacy_write_times_never_supply_missing_observation(self):
        now = datetime.now(timezone.utc)
        offer = NS(sportsbook="FanDuel", line=10.5, over_odds=-110, under_odds=120,
                   updated_at=now, ingested_at=now, provider_observed_at=None)
        prop = NS(is_active=True, odds_event_id="event", game_time=now + timedelta(hours=12), book_offers=[offer])
        missing = offer_availability(prop, "FanDuel", 10.5, "over", now)
        self.assertFalse(missing["actionable"])
        self.assertIsNone(missing["refreshed_at"])
        self.assertEqual(missing["ingested_at"], now.isoformat())
        for minutes, expected in ((30, "available"), (31, "last_known"), (360, "last_known"), (361, "expired")):
            offer.provider_observed_at = now - timedelta(minutes=minutes)
            decision = offer_availability(prop, "FanDuel", 10.5, "over", now)
            self.assertEqual(decision["availability"], expected)
            offer.ingested_at = now + timedelta(minutes=1)
            self.assertEqual(offer_availability(prop, "FanDuel", 10.5, "over", now)["availability"], expected)


if __name__ == "__main__":
    unittest.main()
