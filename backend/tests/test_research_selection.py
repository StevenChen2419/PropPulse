"""Research selection contracts on isolated stores; no providers or app lifespan."""
from datetime import datetime, timedelta, timezone
import os
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import NBAEvidenceRecord, Event, Player, Prop, PropBook, PropBookSnapshot, PlayerGameLog
from app.routers.players import router
import test_ingestion_postgres as pg_fixture


class ResearchSelectionScenarios:
    def fixture(self):
        self.now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.player = Player(name="Research Player", team="Changed Team", team_abbr="CHG", sport="NBA")
        self.other_player = Player(name="Other Player", team="Home", team_abbr="HOM", sport="NBA")
        self.db.add_all([self.player, self.other_player])
        self.db.flush()
        self.event = self.new_event("first", 2)
        self.prop = self.new_prop(self.event)
        self.db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/players")
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(patch.stopall)
        patch("httpx.HTTPTransport.handle_request", side_effect=AssertionError("Provider HTTP forbidden")).start()

    def new_event(self, identity, days):
        event = Event(provider="the_odds_api", sport_key="basketball_nba", provider_event_id=identity,
                      home_team="Home", away_team="Away", scheduled_start_at=self.now + timedelta(days=days))
        self.db.add(event)
        self.db.flush()
        return event

    def new_prop(self, event, player=None):
        prop = Prop(player_id=(player or self.player).id, event_id=event.id if event else None,
                    prop_type="points", line=20.5, sportsbook="FanDuel", is_active=True,
                    game_time=event.scheduled_start_at if event else self.now + timedelta(days=2),
                    odds_event_id=event.provider_event_id if event else "legacy", odds_sport_key="basketball_nba",
                    opponent="Wrong Legacy Opponent", is_home=False)
        self.db.add(prop)
        self.db.flush()
        self.db.add(PropBook(prop_id=prop.id, sportsbook="FanDuel", line=20.5,
                            over_odds=-110, under_odds=-115, provider_observed_at=self.now,
                            ingested_at=self.now, updated_at=self.now))
        self.db.flush()
        return prop

    def get(self, **params):
        self.db.commit()
        return self.client.get(f"/players/{self.player.id}/research", params=params)

    def test_exact_selection_authoritative_context(self):
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["selected_prop"]["id"], self.prop.id)
        self.assertEqual(body["selected_prop"]["event_id"], self.event.id)
        self.assertEqual(body["selected_prop"]["home_team"], "Home")
        self.assertEqual(body["selected_prop"]["away_team"], "Away")
        self.assertEqual(body["selection_source"], "prop_id")
        self.assertTrue(body["selection_available"])
        self.assertTrue(body["selected_prop"]["scheduled_start_at"].endswith("+00:00"))

    def test_exact_sportsbook_line_side_and_stale_snapshot_context(self):
        offer=PropBook(prop_id=self.prop.id,sportsbook='DraftKings',line=22.5,over_odds=120,under_odds=-130,
            provider_observed_at=self.now,ingested_at=self.now)
        self.db.add(offer)
        body=self.get(prop_id=self.prop.id,sportsbook='DraftKings',offer_line=22.5,side='under').json()
        exact=body['exact_line']
        self.assertEqual((exact['line'],exact['side'],exact['selection']['sportsbook']),(22.5,'under','DraftKings'))
        self.assertTrue(exact['selection']['actionable'])
        self.assertEqual(body['selected_prop']['line'],20.5)
        offer.provider_observed_at=self.now-timedelta(hours=7)
        stale=self.get(prop_id=self.prop.id,sportsbook='DraftKings',offer_line=22.5,side='under').json()['exact_line']
        self.assertFalse(stale['selection']['actionable'])
        self.assertEqual(stale['selection']['availability'],'expired')
        self.db.add(PropBookSnapshot(prop_id=self.prop.id,sportsbook='DraftKings',line=22.5,
            over_odds=120,under_odds=-130,captured_at=self.now-timedelta(hours=7)))
        offer.line=24.5
        retained=self.get(prop_id=self.prop.id,sportsbook='DraftKings',offer_line=22.5).json()['exact_line']
        self.assertEqual(retained['line'],22.5)
        self.assertFalse(retained['selection']['actionable'])
        self.assertIsNone(retained['selection']['odds'])

    def test_unknown_or_incomplete_exact_offer_context_is_rejected(self):
        for params,status in [({'sportsbook':'FanDuel'},400),({'offer_line':20.5},400),
                ({'sportsbook':'FanDuel','offer_line':999},400),({'side':'invented'},422),
                ({'sportsbook':'FanDuel','offer_line':'NaN'},422)]:
            with self.subTest(params=params):
                self.assertEqual(self.get(prop_id=self.prop.id,**params).status_code,status)
        self.assertEqual(self.get(sportsbook='FanDuel',offer_line=20.5).status_code,400)

    def test_wrong_player_rejected(self):
        other = self.new_prop(self.event, self.other_player)
        self.assertEqual(self.get(prop_id=other.id).status_code, 400)

    def test_unknown_prop_rejected(self):
        self.assertEqual(self.get(prop_id=str(uuid4())).status_code, 404)

    def test_malformed_prop_rejected(self):
        self.assertEqual(self.get(prop_id="malformed").status_code, 422)

    def test_selection_parameter_conflicts(self):
        for params in ({"prop_type": "points"}, {"line": 20.5}):
            self.assertEqual(self.get(prop_id=self.prop.id, **params).status_code, 400)

    def test_same_market_line_two_events_requires_uuid(self):
        other = self.new_prop(self.new_event("second", 3))
        self.assertEqual(self.get(prop_type="points", line=20.5).status_code, 409)
        body = self.get(prop_id=other.id).json()
        self.assertEqual(body["selected_prop"]["event_id"], other.event_id)

    def test_expired_legacy_selection_does_not_switch_to_later_event(self):
        self.prop.book_offers[0].provider_observed_at = self.now - timedelta(hours=7)
        later = self.new_prop(self.new_event("later-live", 4))
        response = self.get(prop_type="points", line=20.5)
        self.assertEqual(response.status_code, 409)
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["selected_prop"]["id"], self.prop.id)
        self.assertEqual(body["available_props"][0]["id"], later.id)

    def test_unique_unavailable_legacy_selection_rejected(self):
        self.prop.book_offers[0].provider_observed_at = self.now - timedelta(hours=7)
        self.assertEqual(self.get(prop_type="points", line=20.5).status_code, 400)

    def test_conflicting_legacy_opponent_does_not_define_event_split(self):
        self.db.add(PlayerGameLog(player_id=self.player.id, sport="NBA", game_date=self.now - timedelta(days=10),
                                 source="espn_nba", external_game_id="wrong-opponent-history",
                                 opponent="Wrong Legacy Opponent", is_home=True, stats={"points": 25}))
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["selected_prop"]["home_team"], "Home")
        self.assertIsNone(body["splits"]["opponent"]["name"])
        self.assertEqual(body["splits"]["opponent"]["games"], 0)

    def test_shared_comparison_and_alternative_research_scope(self):
        self.db.add(PropBook(prop_id=self.prop.id, sportsbook='DraftKings', line=21.5,
            over_odds=120, under_odds=-140, provider_observed_at=self.now,
            provider_bookmaker_key='draftkings', provider_title='DraftKings'))
        body = self.get(prop_id=self.prop.id, sportsbook='DraftKings', offer_line=21.5, side='under').json()
        exact = body['exact_line']
        self.assertEqual(exact['line'], 21.5)
        self.assertEqual(exact['side'], 'under')
        self.assertEqual(exact['comparison'], body['selected_prop']['comparison'])
        groups = exact['comparison']['groups']
        self.assertEqual({(g['line'], g['side']) for g in groups},
            {(20.5, 'over'), (20.5, 'under'), (21.5, 'over'), (21.5, 'under')})
        self.assertEqual(exact['movement']['status'], 'unavailable')
        self.assertIn('ingestion', exact['movement']['reason'])
        self.assertIsNone(body['line_movement'])

    def test_line_movement_retains_selected_uuid(self):
        self.prop.line = 22.5
        self.prop.book_offers[0].line = 22.5
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["selected_prop"]["id"], self.prop.id)
        self.assertEqual(body["selected_prop"]["line"], 22.5)
        self.assertEqual(body["selected_prop"]["over_odds"], -110)

    def test_expired_selection_keeps_history_and_event(self):
        self.prop.book_offers[0].provider_observed_at = self.now - timedelta(hours=7)
        self.db.add(PlayerGameLog(player_id=self.player.id, sport="NBA", game_date=self.now - timedelta(days=10),
                                 source="espn_nba", external_game_id="history", opponent="Away", is_home=True,
                                 stats={"points": 25}))
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["selected_prop"]["availability"], "expired")
        self.assertIsNone(body["selected_prop"]["over_odds"])
        self.assertFalse(body["selection_available"])
        self.assertEqual(body["available_props"], [])
        self.assertEqual(body["history"]["eligible_games"], 1)
        self.assertEqual(body["selected_prop"]["event_id"], self.event.id)

    def test_expired_primary_book_does_not_switch_to_live_alternative(self):
        self.prop.book_offers[0].provider_observed_at = self.now - timedelta(hours=7)
        self.db.add(PropBook(prop_id=self.prop.id, sportsbook="DraftKings", line=20.5,
                            over_odds=-105, under_odds=-110, provider_observed_at=self.now,
                            ingested_at=self.now, updated_at=self.now))
        body = self.get(prop_id=self.prop.id).json()
        selected = body["selected_prop"]
        self.assertEqual(selected["sportsbook"], "FanDuel")
        self.assertEqual(selected["line"], 20.5)
        self.assertIsNone(selected["over_odds"])
        self.assertIsNone(selected["under_odds"])
        self.assertEqual(selected["availability"], "expired")
        self.assertFalse(selected["actionable"])
        self.assertFalse(body["selection_available"])
        self.assertEqual(selected["sportsbook_offers"][0]["sportsbook"], "DraftKings")
        self.assertTrue(selected["sportsbook_offers"][0]["actionable"])

    def test_alternate_line_does_not_replace_primary_line(self):
        self.prop.book_offers[0].line = 22.5
        body = self.get(prop_id=self.prop.id).json()
        selected = body["selected_prop"]
        self.assertEqual(selected["sportsbook"], "FanDuel")
        self.assertEqual(selected["line"], 20.5)
        self.assertIsNone(selected["over_odds"])
        self.assertIsNone(selected["under_odds"])
        self.assertEqual(selected["availability"], "market_unavailable")
        self.assertFalse(selected["actionable"])
        self.assertFalse(body["selection_available"])
        self.assertEqual(selected["sportsbook_offers"][0]["line"], 22.5)

    def test_search_uses_event_schedule_with_missing_legacy_time(self):
        self.prop.game_time = None
        self.db.commit()
        response = self.client.get("/players/search", params={"q": "Research Player"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["players"][0]["id"], self.player.id)

    def test_started_selection_retained_without_switch(self):
        self.event.scheduled_start_at = self.now - timedelta(hours=1)
        self.new_prop(self.new_event("next", 4))
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["selected_prop"]["id"], self.prop.id)
        self.assertEqual(body["selected_prop"]["availability"], "game_started")
        self.assertFalse(body["selection_available"])

    def test_no_history_preserves_availability(self):
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["history"]["status"], "no_history")
        self.assertTrue(body["selection_available"])

    def test_generic_default_is_earliest_and_deterministic(self):
        self.new_prop(self.new_event("later", 3))
        first = self.get().json()
        second = self.get().json()
        self.assertEqual(first["selected_prop"]["id"], self.prop.id)
        self.assertEqual(second["selected_prop"]["id"], self.prop.id)
        self.assertEqual(first["selection_source"], "default")

    def test_default_ties_use_prop_uuid(self):
        other = self.new_prop(self.event)
        body = self.get().json()
        self.assertEqual(body["selected_prop"]["id"], min(self.prop.id, other.id))

    def test_history_cutoff_uses_event_schedule(self):
        self.prop.game_time = self.now - timedelta(days=10)
        self.event.scheduled_start_at = self.now - timedelta(days=2)
        self.db.add(PlayerGameLog(player_id=self.player.id, sport="NBA", game_date=self.now - timedelta(days=5),
                                 source="espn_nba", external_game_id="corrected-history", opponent="Away",
                                 is_home=True, stats={"points": 25}))
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["history"]["eligible_games"], 1)
        self.assertEqual(body["selected_prop"]["availability"], "game_started")

    def test_schedule_corrected_context_uses_event(self):
        self.event.scheduled_start_at += timedelta(days=1)
        body = self.get(prop_id=self.prop.id).json()
        selected = body["selected_prop"]
        self.assertEqual(selected["event_id"], self.event.id)
        self.assertEqual(selected["game_time"], self.event.scheduled_start_at.replace(tzinfo=timezone.utc).isoformat())

    def test_unlinked_selection_has_no_event_identity(self):
        legacy = self.new_prop(None)
        body = self.get(prop_id=legacy.id).json()
        self.assertIsNone(body["selected_prop"]["event_id"])
        self.assertNotEqual(body["selected_prop"]["identity_source"], "authoritative")
        self.assertIsNone(body["selected_prop"]["provider"])

    def test_inactive_selection_retained(self):
        self.prop.is_active = False
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["selected_prop"]["id"], self.prop.id)
        self.assertFalse(body["selection_available"])


class ResearchSelectionSQLiteTests(ResearchSelectionScenarios, unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine, tables=[model.__table__ for model in
            (Event, Player, Prop, PropBook, PropBookSnapshot, PlayerGameLog, NBAEvidenceRecord)])
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.fixture()


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit isolated PostgreSQL URL unset")
class ResearchSelectionPostgresTests(ResearchSelectionScenarios, unittest.TestCase):
    setUpClass = classmethod(pg_fixture.IngestionPostgresTests.setUpClass.__func__)
    remove_schema = pg_fixture.IngestionPostgresTests.remove_schema

    def setUp(self):
        pg_fixture.IngestionPostgresTests.setUp(self)
        Base.metadata.create_all(self.engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.fixture()
