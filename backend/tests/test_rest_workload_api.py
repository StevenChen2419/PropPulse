"""Identical API scenarios on isolated SQLite and opt-in disposable PostgreSQL."""
from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event as sql_event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import NBAEvidenceRecord, Event, Player, PlayerGameLog, Prop, PropBook, PropBookSnapshot
from app.routers.players import router
import test_ingestion_postgres as pg_fixture


class RestApiScenarios:
    def fixture(self):
        self.now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.player = Player(name="Research", sport="NBA", team="Changed Team", team_abbr="CHG")
        self.other = Player(name="Other", sport="NBA", team="Home", team_abbr="HOM")
        self.event = Event(provider="the_odds_api", sport_key="basketball_nba", provider_event_id="opaque",
                           home_team="Home", away_team="Away", scheduled_start_at=self.now + timedelta(days=2))
        self.db.add_all([self.player, self.other, self.event])
        self.db.flush()
        self.prop = Prop(player_id=self.player.id, event_id=self.event.id, prop_type="points", line=20.5,
                         sportsbook="FanDuel", game_time=self.now + timedelta(days=99), opponent="Conflicting", is_active=True)
        self.db.add(self.prop)
        self.db.flush()
        self.db.add(PlayerGameLog(player_id=self.player.id, sport="NBA", source="espn_nba", external_game_id="game",
                                  game_date=self.now - timedelta(days=1), stats={"points": 30, "minutes": 32}))
        self.db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/players")
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        blocker = patch("httpx.HTTPTransport.handle_request", side_effect=AssertionError("External HTTP forbidden"))
        blocker.start()
        self.addCleanup(blocker.stop)

    def get(self, suffix="rest-workload", **params):
        return self.client.get(f"/players/{self.player.id}/{suffix}", params=params)

    def test_no_offer_required_and_no_data_mutations(self):
        writes = []
        def record(conn, cursor, statement, *args):
            if statement.strip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}:
                writes.append(statement)
        sql_event.listen(self.engine, "before_cursor_execute", record)
        self.addCleanup(sql_event.remove, self.engine, "before_cursor_execute", record)
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workload"]["l5"]["average_minutes"], 32)
        self.assertEqual(writes, [])

    def test_exact_expired_prop_preserved(self):
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["reference"]["prop_id"], self.prop.id)
        self.assertEqual(body["reference"]["event_id"], self.event.id)
        self.assertEqual(body["reference"]["at"], self.event.scheduled_start_at.replace(tzinfo=timezone.utc).isoformat())
        research = self.get("research", prop_id=self.prop.id).json()
        self.assertEqual(research["selected_prop"]["id"], self.prop.id)
        self.assertFalse(research["selection_available"])
        self.assertEqual(research["rest_workload"]["reference"]["prop_id"], self.prop.id)
        self.assertEqual(research["trends"]["l5"]["hit_rate"], 1)

    def test_player_only_research_without_live_props(self):
        body = self.get("research").json()
        self.assertIsNone(body["selected_prop"])
        self.assertIsNone(body["history"])
        self.assertEqual(body["rest_workload"]["coverage"]["eligible_games"], 1)

    def test_verified_connector_unavailable_is_unknown(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        verified = response.json()["verified"]
        self.assertEqual(verified["status"], "unknown")
        self.assertIsNone(verified["last_confirmed_appearance"])
        self.assertIsNone(verified["last_completed_team_game"])
        self.assertIsNone(verified["team_back_to_back"])
        self.assertIsNone(verified["confirmed_missed_games"])
        self.assertIsNone(verified["partial_missed_games_lower_bound"])
        self.assertFalse(verified["schedule_complete"])

    def test_retained_stats_do_not_promote_confirmed_participation(self):
        log = self.db.query(PlayerGameLog).filter(PlayerGameLog.player_id == self.player.id).one()
        log.stats = {"minutes": 32, "points": 0, "completed": True}
        self.db.commit()
        body = self.get("research", prop_id=self.prop.id).json()
        self.assertEqual(body["rest_workload"]["coverage"]["eligible_games"], 1)
        self.assertEqual(body["rest_workload"]["verified"]["status"], "unknown")
        self.assertIsNone(body["rest_workload"]["verified"]["last_confirmed_appearance"])

    def test_verified_unknown_keeps_exact_uuid_and_reference(self):
        body = self.get(prop_id=self.prop.id).json()
        self.assertEqual(body["reference"]["prop_id"], self.prop.id)
        self.assertEqual(body["reference"]["event_id"], self.event.id)
        self.assertEqual(body["verified"]["reference_at"], body["reference"]["at"])
        self.assertIsNone(body["verified"]["context_team_id"])
        self.assertEqual(body["verified"]["provenance"], [])

    def test_event_only_authoritative_context(self):
        body = self.get(event_id=self.event.id).json()
        self.assertEqual(body["reference"]["event_id"], self.event.id)
        self.assertIsNone(body["reference"]["prop_id"])
        self.assertFalse(body["coverage"]["schedule_complete"])

    def test_prop_event_mismatch_rejected(self):
        self.assertEqual(self.get(prop_id=self.prop.id, event_id=str(uuid4())).status_code, 409)

    def test_unlinked_event_not_assumed_from_current_team(self):
        other = Event(provider="the_odds_api", sport_key="basketball_nba", provider_event_id="other",
                      home_team="Changed Team", away_team="Away", scheduled_start_at=self.now + timedelta(days=3))
        self.db.add(other)
        self.db.commit()
        self.assertEqual(self.get(event_id=other.id).status_code, 400)

    def test_unknown_and_malformed_context(self):
        self.assertEqual(self.get(prop_id=str(uuid4())).status_code, 404)
        self.assertEqual(self.get(event_id=str(uuid4())).status_code, 404)
        self.assertEqual(self.get(prop_id="bad").status_code, 422)
        self.assertEqual(self.get(event_id="bad").status_code, 422)
        self.assertEqual(self.client.get(f"/players/{uuid4()}/rest-workload").status_code, 404)

    def test_other_player_prop_rejected(self):
        self.prop.player_id = self.other.id
        self.db.commit()
        self.assertEqual(self.get(prop_id=self.prop.id).status_code, 400)

    def test_legacy_prop_not_a_verified_schedule(self):
        prop = Prop(player_id=self.player.id, prop_type="points", line=30, game_time=self.now + timedelta(days=90))
        self.db.add(prop)
        self.db.commit()
        body = self.get(prop_id=prop.id).json()
        self.assertEqual(body["reference"]["prop_id"], prop.id)
        self.assertEqual(body["reference"]["source"], "as_of")
        self.assertIsNone(body["reference"]["event_id"])

    def test_event_sport_mismatch_rejected(self):
        event = Event(provider="the_odds_api", sport_key="baseball_mlb", provider_event_id="wrong-sport",
                      home_team="Home", away_team="Away", scheduled_start_at=self.now + timedelta(days=2))
        self.db.add(event)
        self.db.flush()
        prop = Prop(player_id=self.player.id, event_id=event.id, prop_type="points", line=20)
        self.db.add(prop)
        self.db.commit()
        self.assertEqual(self.get(event_id=event.id).status_code, 400)
        self.assertEqual(self.get(prop_id=prop.id).status_code, 400)
        body = self.get("research", prop_id=prop.id).json()
        self.assertEqual(body["rest_workload"]["reference"]["source"], "as_of")


class RestWorkloadSqliteTests(RestApiScenarios, unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine, tables=[model.__table__ for model in
                                 (Player, Event, Prop, PropBook, PropBookSnapshot, PlayerGameLog, NBAEvidenceRecord)])
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.db.close)
        self.fixture()


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit disposable PostgreSQL URL required")
class RestWorkloadPostgresTests(RestApiScenarios, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pg_fixture.IngestionPostgresTests.setUpClass()

    def setUp(self):
        fixture = pg_fixture.IngestionPostgresTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.engine = fixture.engine
        Base.metadata.create_all(self.engine, tables=[PlayerGameLog.__table__])
        self.db = fixture.Session()
        self.addCleanup(self.db.close)
        self.fixture()
