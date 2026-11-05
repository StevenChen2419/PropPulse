"""Game API regressions; isolated ASGI apps, stores and blocked external HTTP."""
from datetime import datetime, timedelta, timezone
import os
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event as sql_event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_optional_user
from app.database import Base, get_db
from app.models import Event, Player, Prop, PropBook, PlayerGameLog
from app.routers.props import router
from app.services.game_identity_service import prop_context
from app.services.game_log_fields import provider_season
from app.schemas import PropOut
import test_ingestion_postgres as pg_fixture


class EventApiScenarios:
    def fixture(self):
        self.now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.event = self.new_event()
        self.players = []
        self.props = []
        for index, team in enumerate(("Away", "Home")):
            player = Player(name=f"Player {index}", team=team, team_abbr=team, sport="NBA")
            self.db.add(player)
            self.db.flush()
            self.players.append(player)
            for market in ("points", "assists", "rebounds", "threes", "blocks"):
                self.props.append(self.new_prop(player, self.event, market=market, home=bool(index)))
        self.db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/props")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_optional_user] = lambda: None
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        blocker = patch("httpx.HTTPTransport.handle_request", side_effect=AssertionError("External HTTP forbidden"))
        blocker.start()
        self.addCleanup(blocker.stop)

    def new_event(self, identity="provider-event", **changes):
        event = Event(**{"provider": "the_odds_api", "sport_key": "basketball_nba",
                         "provider_event_id": identity, "home_team": "Home", "away_team": "Away",
                         "scheduled_start_at": self.now + timedelta(days=2), **changes})
        self.db.add(event)
        self.db.flush()
        return event

    def new_prop(self, player, event=None, market="points", home=False, **changes):
        prop = Prop(**{"player_id": player.id, "event_id": event.id if event else None,
                       "prop_type": market, "line": 20.5, "sportsbook": "FanDuel",
                       "game_time": event.scheduled_start_at if event else self.now + timedelta(days=2),
                       "odds_event_id": event.provider_event_id if event else "legacy-event",
                       "odds_sport_key": event.sport_key if event else "basketball_nba",
                       "is_home": home, "opponent": "Away" if home else "Home", **changes})
        self.db.add(prop)
        self.db.flush()
        self.db.add(PropBook(prop_id=prop.id, sportsbook="FanDuel", line=20.5,
                            over_odds=-110, under_odds=-115, provider_observed_at=self.now,
                            ingested_at=self.now))
        self.db.flush()
        return prop

    def get(self, route, **params):
        self.db.commit()
        return self.client.get("/props/" + route, params=params)

    def games(self):
        return self.get("games").json()["games"]

    def history(self):
        # Use current-season completed observations; current season is intentionally
        # independent from the wall-clock year for basketball ending-year semantics.
        season = provider_season("NBA", self.event.scheduled_start_at)
        for player in self.players:
            for n in range(12):
                self.db.add(PlayerGameLog(player_id=player.id, sport="NBA", external_game_id=str(n),
                    source="espn_nba", game_date=self.now - timedelta(days=n + 1),
                    stats={"points": 30, "assists": 30, "season": season}, opponent="Home", is_home=True))
        self.db.flush()

    def test_both_teams_and_ten_markets_one_event_card(self):
        games = self.games()
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["event_id"], self.event.id)
        self.assertEqual(games[0]["prop_count"], 10)
        self.assertEqual(games[0]["identity_source"], "authoritative")
        self.assertEqual((games[0]["away_team"], games[0]["home_team"]), ("Away", "Home"))
        self.assertTrue(games[0]["has_eligible_props"])

    def test_team_changes_and_conflicting_prop_fields_do_not_split_event(self):
        self.players[0].team = "Traded Team"
        self.props[0].opponent = "Wrong Opponent"
        self.props[1].is_home = True
        self.props[2].game_time += timedelta(days=5)
        games = self.games()
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["prop_count"], 10)
        self.assertEqual(games[0]["away_team"], "Away")

    def test_corrected_schedule_and_stale_prop_time_use_stable_uuid(self):
        self.event.scheduled_start_at += timedelta(days=3)
        for prop in self.props:
            prop.game_time = self.now - timedelta(days=1)
        body = self.get("game", event_id=self.event.id).json()
        self.assertEqual(body["event_id"], self.event.id)
        self.assertEqual(body["total_props"], 10)
        self.assertEqual(body["game_time"], self.event.scheduled_start_at.replace(tzinfo=timezone.utc).isoformat())

    def test_same_matchup_different_dates_not_merged(self):
        second = self.new_event("second", scheduled_start_at=self.now + timedelta(days=3))
        self.new_prop(self.players[0], second)
        self.assertEqual({g["event_id"] for g in self.games()}, {self.event.id, second.id})

    def test_namespace_identity_not_merged(self):
        second = self.new_event(provider="other_provider")
        third = self.new_event(sport_key="baseball_mlb")
        self.new_prop(self.players[0], second)
        self.new_prop(self.players[0], third)
        games = self.games()
        self.assertEqual(len(games), 3)
        self.assertEqual({g["sport"] for g in games}, {"NBA", "MLB"})
        key = prop_context(self.props[0])["game_key"]
        self.assertEqual(self.get("game", game_key=key).status_code, 409)

    def test_empty_event_with_no_props_remains_addressable(self):
        empty = self.new_event("empty")
        body = self.get("game", event_id=empty.id).json()
        self.assertEqual(body["event_id"], empty.id)
        self.assertEqual(body["props"], [])
        self.assertFalse(body["actionable"])
        self.assertFalse(body["has_eligible_props"])

    def test_expired_event_detail_keeps_metadata_not_prices(self):
        for prop in self.props:
            prop.book_offers[0].provider_observed_at -= timedelta(hours=7)
        body = self.get("game", event_id=self.event.id).json()
        self.assertEqual(body["props"], [])
        self.assertEqual(body["identity_source"], "authoritative")
        self.assertEqual(self.games(), [])

    def test_started_event_cannot_reactivate_from_future_legacy_time(self):
        self.event.scheduled_start_at = self.now - timedelta(seconds=1)
        body = self.get("game", event_id=self.event.id).json()
        self.assertEqual(body["total_props"], 0)
        self.assertFalse(body["actionable"])
        self.assertEqual(self.get("feed", event_id=self.event.id).json()["props"], [])

    def test_error_contracts(self):
        for route in ("game", "feed", "discover"):
            self.assertEqual(self.get(route, event_id=str(uuid4())).status_code, 404)
            self.assertEqual(self.get(route, event_id="invalid").status_code, 422)
            self.assertEqual(self.get(route, event_id=self.event.id, sport="MLB").status_code, 400)
            self.assertEqual(self.get(route, event_id=self.event.id, game_key="bad").status_code, 400)
        self.assertEqual(self.get("game").status_code, 400)
        self.assertEqual(self.get("game", game_key="bad").status_code, 400)

    def test_feed_event_filter_excludes_unlinked_and_other_events(self):
        legacy = self.new_prop(self.players[0])
        self.new_prop(self.players[0], self.new_event("second"))
        body = self.get("feed", event_id=self.event.id).json()
        self.assertEqual(body["total"], 10)
        self.assertEqual({p["event_id"] for p in body["props"]}, {self.event.id})
        self.assertNotIn(legacy.id, {p["id"] for p in body["props"]})

    def test_discover_event_filter_preserves_history_gate(self):
        self.new_prop(self.players[0])
        self.assertEqual(self.get("discover", event_id=self.event.id).json()["props"], [])
        self.history()
        body = self.get("discover", event_id=self.event.id).json()
        self.assertGreater(body["total"], 0)
        self.assertEqual({p["event_id"] for p in body["props"]}, {self.event.id})
        for prop in self.props:
            prop.book_offers[0].provider_observed_at -= timedelta(hours=7)
        self.assertEqual(self.get("discover", event_id=self.event.id).json()["props"], [])

    def test_exact_line_comparison_unchanged(self):
        prop = self.props[0]
        self.db.add(PropBook(prop_id=prop.id, sportsbook="DraftKings", line=22.5,
                            over_odds=200, under_odds=-110, provider_observed_at=self.now))
        props = self.get("feed", event_id=self.event.id).json()["props"]
        row = next(p for p in props if p["id"] == prop.id)
        self.assertEqual(row["best_over"]["line"], 20.5)
        self.assertEqual(row["best_over"]["sportsbook"], "FanDuel")
        self.assertEqual(len(row["sportsbook_offers"]), 2)

    def test_unlinked_browsing_and_safe_legacy_key(self):
        legacy = self.new_prop(self.players[0], game_time=self.now + timedelta(days=4))
        key = prop_context(legacy)["game_key"]
        body = self.get("game", game_key=key).json()
        self.assertEqual(body["total_props"], 1)
        self.assertEqual(body["identity_source"], "legacy")
        self.assertIsNone(body["event_id"])
        self.assertIsNone(body["provider"])
        self.assertIn(legacy.id, {p["id"] for p in self.get("feed").json()["props"]})

    def test_missing_provider_identity_not_fabricated_but_explicit_research_possible(self):
        legacy = self.new_prop(self.players[0], odds_event_id=None)
        context = prop_context(legacy)
        self.assertIsNone(context["event_id"])
        self.assertIsNone(context["provider_event_id"])
        self.assertNotIn(legacy.id, {p["id"] for p in self.get("feed").json()["props"]})

    def test_mixed_linked_and_unlinked_key_rejected(self):
        self.new_prop(self.players[0])
        key = prop_context(self.props[0])["game_key"]
        for route in ("game", "feed", "discover"):
            self.assertEqual(self.get(route, game_key=key).status_code, 409)
        self.assertEqual(self.get("game", event_id=self.event.id).json()["total_props"], 10)

    def test_legacy_same_key_multiple_provider_ids_rejected(self):
        first = self.new_prop(self.players[0], game_time=self.now + timedelta(days=4))
        self.new_prop(self.players[0], game_time=first.game_time, odds_event_id="different")
        key = prop_context(first)["game_key"]
        self.assertEqual(self.get("game", game_key=key).status_code, 409)

    def test_conflicting_legacy_namespace_excluded_from_cards_but_browsable(self):
        first = self.new_prop(self.players[0], game_time=self.now + timedelta(days=4))
        self.new_prop(self.players[0], game_time=first.game_time, opponent="Different")
        self.assertEqual(len(self.games()), 1)
        self.assertEqual(self.get("game", game_key=prop_context(first)["game_key"]).status_code, 409)
        self.assertEqual(self.get("feed").json()["total"], 12)

    def test_incomplete_legacy_context_only_browsable(self):
        legacy = self.new_prop(self.players[0], opponent=None)
        self.assertEqual(prop_context(legacy)["identity_source"], "unresolved")
        self.assertIsNone(prop_context(legacy)["game_key"])
        self.assertEqual(len(self.games()), 1)
        self.assertIn(legacy.id, {p["id"] for p in self.get("feed").json()["props"]})

    def test_legacy_alias_for_authoritative_event_and_timezone_equivalence(self):
        key = prop_context(self.props[0])["game_key"]
        body = self.get("game", game_key=key).json()
        self.assertEqual(body["event_id"], self.event.id)
        parts = key.split("|")
        parts[1] += "+00:00"
        self.assertEqual(self.get("game", game_key="|".join(parts)).json()["event_id"], self.event.id)

    def test_todays_games_remains_upcoming_compatibility(self):
        body = self.get("todays-games").json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["event_id"], self.event.id)
        self.assertEqual(body[0]["available_props"] if "available_props" in body[0] else body[0]["prop_count"], 10)

    def test_feed_cards_detail_agree_on_context_and_utc(self):
        card = self.games()[0]
        detail = self.get("game", event_id=self.event.id).json()
        feed = self.get("feed", event_id=self.event.id).json()["props"][0]
        for key in ("event_id", "provider", "provider_event_id", "sport_key", "scheduled_start_at",
                    "sport", "identity_source", "game_key", "away_team", "home_team", "game_time"):
            self.assertEqual(card[key], detail[key])
            self.assertEqual(card[key], feed[key])
        self.assertTrue(card["scheduled_start_at"].endswith("+00:00"))
        validated = PropOut.model_validate(feed)
        self.assertEqual(str(validated.event_id), self.event.id)
        self.assertEqual(validated.scheduled_start_at.utcoffset(), timedelta(0))

    def test_ingestion_status_uses_event_schedule_with_null_legacy_time(self):
        self.props[0].game_time = None
        with patch("app.routers.props.read_ingestion_status", return_value={}):
            response = self.get("ingestion-status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_offer_status"]["game_time"],
                         self.event.scheduled_start_at.replace(tzinfo=timezone.utc).isoformat())

    def test_ingestion_status_loads_events_without_lazy_queries(self):
        self.new_prop(self.players[0], self.new_event("second-status"))
        self.new_prop(self.players[0], self.new_event("third-status"))
        self.db.commit()
        self.db.expunge_all()
        statements = []
        def record(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        engine = self.db.get_bind()
        sql_event.listen(engine, "before_cursor_execute", record)
        try:
            with patch("app.routers.props.read_ingestion_status", return_value={}):
                response = self.client.get("/props/ingestion-status")
        finally:
            sql_event.remove(engine, "before_cursor_execute", record)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_prop_count"], 12)
        self.assertEqual(len(statements), 1, "Event schedule evaluation must not issue per-Event SELECTs")

    def test_known_empty_event_does_not_absorb_unlinked_card(self):
        empty = self.new_event("empty", scheduled_start_at=self.now + timedelta(days=4))
        legacy = self.new_prop(self.players[0], game_time=empty.scheduled_start_at)
        self.assertEqual(len(self.games()), 1)
        self.assertEqual(self.get("game", game_key=prop_context(legacy)["game_key"]).status_code, 409)
        self.assertEqual(self.get("game", event_id=empty.id).json()["props"], [])


class EventApiSQLiteTests(EventApiScenarios, unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine, tables=[m.__table__ for m in (Event, Player, Prop, PropBook, PlayerGameLog)])
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        # PostgreSQL suite below exercises the real ranking query and ARRAY models.
        rank = patch("app.routers.props.rank_props", side_effect=lambda props, user, db: [
            {"prop": p, "fatigue": None, "rank_score": 0, "reasons": [], "line_movement": 0} for p in props])
        rank.start()
        self.addCleanup(rank.stop)
        self.fixture()


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit isolated PostgreSQL URL unset")
class EventApiPostgresTests(EventApiScenarios, unittest.TestCase):
    setUpClass = classmethod(pg_fixture.IngestionPostgresTests.setUpClass.__func__)
    remove_schema = pg_fixture.IngestionPostgresTests.remove_schema

    def setUp(self):
        pg_fixture.IngestionPostgresTests.setUp(self)
        Base.metadata.create_all(self.engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.fixture()
