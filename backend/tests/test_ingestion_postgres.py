"""Explicitly opt-in PostgreSQL checks, never the configured application database.

Set PROPPULSE_TEST_POSTGRES_URL to a disposable database whose name starts with
proppulse_test_. Each test owns a random schema and drops only that schema.
No provider HTTP requests or application lifespan are used.
"""

from datetime import datetime, timedelta
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import MetaData, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.database import Base
from app.models import Event, NBAEvidenceRecord, Player, PlayerGameLog, Prop, PropBook, PropBookSnapshot, SavedProp, Slip, SlipItem, User
from app.services.ingestion_control import odds_ingestion_lock
from scripts.fetch_odds import apply_updates_for_sport, make_sport_status
from scripts import fetch_odds


TEST_URL = os.environ.get("PROPPULSE_TEST_POSTGRES_URL")


@unittest.skipUnless(TEST_URL, "PROPPULSE_TEST_POSTGRES_URL is unset; no PostgreSQL connection attempted")
class IngestionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Validate before creating any engine or attempting any network access.
        try:
            target = make_url(TEST_URL)
        except Exception:
            raise RuntimeError("Invalid explicit PostgreSQL test URL") from None
        if (target.get_backend_name() != "postgresql" or not target.database
                or not target.database.startswith("proppulse_test_")):
            raise RuntimeError("PostgreSQL integration tests require a proppulse_test_ database")
        cls.target = target

    def setUp(self):
        self.schema = "proppulse_test_" + uuid.uuid4().hex
        self.admin = create_engine(self.target, poolclass=NullPool, echo=False)
        self.addCleanup(self.admin.dispose)
        with self.admin.begin() as connection:
            connection.execute(CreateSchema(self.schema))
        self.addCleanup(self.remove_schema)
        self.engine = create_engine(self.target, poolclass=NullPool, echo=False)
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def set_isolated_search_path(dbapi_connection, _record):
            # Generated identifier contains only a fixed prefix and UUID hex.
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute('SET search_path TO "' + self.schema + '"')
                dbapi_connection.commit()
            finally:
                cursor.close()

        tables = [model.__table__ for model in
                  (Event, User, Player, Prop, PropBook, PropBookSnapshot, SavedProp, Slip, SlipItem, NBAEvidenceRecord)]
        Base.metadata.create_all(self.engine, tables=tables)
        self.Session = sessionmaker(bind=self.engine)
        self.now = datetime.utcnow().replace(microsecond=0)

    def remove_schema(self):
        # No arbitrary database/schema names and no application-schema cleanup.
        if not self.schema.startswith("proppulse_test_") or len(self.schema) != len("proppulse_test_") + 32:
            raise RuntimeError("Refusing cleanup of unexpected schema")
        with self.admin.begin() as connection:
            connection.execute(DropSchema(self.schema, cascade=True))

    def seed_selection(self):
        with self.Session.begin() as session:
            player = Player(name="Test Player", team="Home Team", team_abbr="HOM", sport="MLB")
            user = User(email="isolated@example.invalid", hashed_password="test-only")
            session.add_all([player, user])
            session.flush()
            prop = Prop(player_id=player.id, prop_type="hits", line=1.5, sportsbook="FanDuel",
                        odds_event_id="event-a", odds_sport_key="baseball_mlb",
                        game_time=self.now + timedelta(hours=3), opponent="Away Team", is_active=True)
            slip = Slip(user_id=user.id)
            session.add_all([prop, slip])
            session.flush()
            offer = PropBook(prop_id=prop.id, sportsbook="FanDuel", line=1.5,
                             over_odds=-110, under_odds=-110, provider_bookmaker_key="fanduel",
                             provider_title="FanDuel", provider_observed_at=self.now,
                             ingested_at=self.now, updated_at=self.now)
            historical = PropBookSnapshot(prop_id=prop.id, sportsbook="FanDuel", line=1.5,
                                          over_odds=-110, under_odds=-110, captured_at=self.now)
            saved = SavedProp(user_id=user.id, prop_id=prop.id)
            choice = SlipItem(slip_id=slip.id, prop_id=prop.id, side="over", sportsbook="FanDuel", line=1.5)
            session.add_all([offer, historical, saved, choice])
            session.flush()
            return {"player": player.id, "prop": prop.id, "offer": offer.id, "snapshot": historical.id,
                    "saved": saved.id, "choice": choice.id, "user": user.id, "slip": slip.id}

    def row(self, **changes):
        return dict(player_name="Test Player", prop_type="hits", event_id="event-a",
                    game_time=(self.now + timedelta(hours=3)).isoformat() + "Z",
                    home_team="Home Team", away_team="Away Team", sportsbook="FanDuel",
                    provider_bookmaker_key="fanduel", provider_observed_at=self.now,
                    **{"line": 2.5, "over_odds": 120, "under_odds": -130, **changes})

    def reconcile(self, session, rows):
        return apply_updates_for_sport(session, "baseball_mlb", rows,
                                       make_sport_status("baseball_mlb"))

    def assert_selection_preserved(self, session, ids):
        self.assertIsNotNone(session.get(SavedProp, ids["saved"]))
        choice = session.get(SlipItem, ids["choice"])
        self.assertEqual((choice.prop_id, choice.sportsbook, choice.line, choice.side),
                         (ids["prop"], "FanDuel", 1.5, "over"))
        self.assertIsNotNone(session.get(PropBookSnapshot, ids["snapshot"]))

    def test_shared_advisory_lock_contends_across_connections_and_releases(self):
        with odds_ingestion_lock(self.engine) as manual:
            self.assertTrue(manual)
            with odds_ingestion_lock(self.engine) as automatic:
                self.assertFalse(automatic)
            # Independent transactions/commits do not release the owner's lock.
            with self.engine.begin() as connection:
                connection.execute(text("SELECT 1"))
            with odds_ingestion_lock(self.engine) as competing_worker:
                self.assertFalse(competing_worker)
        with odds_ingestion_lock(self.engine) as next_worker:
            self.assertTrue(next_worker)

    def test_shared_lock_releases_after_exception(self):
        with self.assertRaisesRegex(RuntimeError, "controlled test failure"):
            with odds_ingestion_lock(self.engine) as acquired:
                self.assertTrue(acquired)
                raise RuntimeError("controlled test failure")
        with odds_ingestion_lock(self.engine) as acquired:
            self.assertTrue(acquired)

    def test_reconciliation_flush_then_rollback_preserves_offer_snapshot_and_choices(self):
        ids = self.seed_selection()
        with self.assertRaisesRegex(RuntimeError, "before commit"):
            with self.Session.begin() as session:
                self.reconcile(session, [self.row()])
                session.flush()
                self.assertEqual(session.get(PropBook, ids["offer"]).line, 2.5)
                self.assertEqual(session.query(PropBookSnapshot).count(), 2)
                raise RuntimeError("before commit")
        with self.Session() as session:
            self.assertEqual(session.get(PropBook, ids["offer"]).line, 1.5)
            self.assertEqual(session.get(Prop, ids["prop"]).line, 1.5)
            self.assertEqual(session.query(PropBookSnapshot).count(), 1)
            self.assert_selection_preserved(session, ids)

    def test_repeated_reconciliation_and_omitted_coverage_preserve_records(self):
        ids = self.seed_selection()
        for _ in range(2):
            with self.Session.begin() as session:
                self.reconcile(session, [self.row()])
        with self.Session.begin() as session:
            self.reconcile(session, [])
        with self.Session() as session:
            self.assertEqual(session.query(PropBook).count(), 1)
            self.assertEqual(session.query(Prop).count(), 1)
            self.assertEqual(session.query(PropBookSnapshot).count(), 2)
            self.assertEqual(session.get(PropBook, ids["offer"]).line, 2.5)
            self.assertEqual(session.get(PropBook, ids["offer"]).provider_observed_at, self.now)
            self.assert_selection_preserved(session, ids)

    def upgrade_isolated_schema(self):
        from alembic import command
        from alembic.config import Config

        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def test_alembic_fresh_schema_initializes_all_models_without_autogenerate_diffs(self):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext

        # This engine's search_path is restricted to this test's random schema.
        Base.metadata.drop_all(self.engine)
        self.upgrade_isolated_schema()
        with self.engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            self.assertTrue(set(Base.metadata.tables).issubset(tables))
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            self.assertEqual(compare_metadata(context, Base.metadata), [])
            self.assertEqual(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
                             "20261022_05")

    def test_full_legacy_schema_upgrade_preserves_records_and_unknown_observation(self):
        Base.metadata.drop_all(self.engine)
        legacy = MetaData()
        for table in Base.metadata.sorted_tables:
            table.to_metadata(legacy)
        # Freeze a genuinely pre-Event legacy fixture; do not accidentally adopt
        # new columns merely because the bootstrap imports today's models.
        props_table = legacy.tables["props"]
        for foreign_key in list(props_table.c.event_id.foreign_keys):
            props_table.constraints.discard(foreign_key.constraint)
            props_table.foreign_keys.discard(foreign_key)
        for index in list(props_table.indexes):
            if "event_id" in index.columns:
                props_table.indexes.remove(index)
        props_table._columns.remove(props_table.c.event_id)
        legacy.remove(legacy.tables["events"])
        for name in ("provider_bookmaker_key", "provider_title", "provider_observed_at", "ingested_at"):
            legacy.tables["prop_books"]._columns.remove(legacy.tables["prop_books"].c[name])
        legacy.create_all(self.engine)
        ids = {name: str(uuid.uuid4()) for name in ("player", "user", "prop", "offer", "snapshot", "saved", "slip", "choice")}
        old_write = self.now - timedelta(hours=2)
        with self.engine.begin() as connection:
            connection.execute(legacy.tables["players"].insert().values(
                id=ids["player"], name="Legacy Player", team="Home Team", team_abbr="HOM", sport="MLB"))
            connection.execute(legacy.tables["users"].insert().values(
                id=ids["user"], email="legacy@example.invalid", hashed_password="test-only"))
            connection.execute(legacy.tables["props"].insert().values(
                id=ids["prop"], player_id=ids["player"], prop_type="hits", line=1.5,
                sportsbook="FanDuel", odds_event_id="legacy-event", odds_sport_key="baseball_mlb",
                game_time=self.now + timedelta(hours=3)))
            connection.execute(legacy.tables["prop_books"].insert().values(
                id=ids["offer"], prop_id=ids["prop"], sportsbook="FanDuel", line=1.5,
                over_odds=-110, under_odds=120, updated_at=old_write))
            connection.execute(legacy.tables["prop_book_snapshots"].insert().values(
                id=ids["snapshot"], prop_id=ids["prop"], sportsbook="FanDuel", line=1.5,
                over_odds=-110, under_odds=120, captured_at=old_write))
            connection.execute(legacy.tables["saved_props"].insert().values(
                id=ids["saved"], prop_id=ids["prop"], user_id=ids["user"]))
            connection.execute(legacy.tables["slips"].insert().values(id=ids["slip"], user_id=ids["user"]))
            connection.execute(legacy.tables["slip_items"].insert().values(
                id=ids["choice"], slip_id=ids["slip"], prop_id=ids["prop"],
                sportsbook="FanDuel", line=1.5, side="over"))
        self.upgrade_isolated_schema()
        self.upgrade_isolated_schema()  # A second head upgrade must be a no-op.
        with self.engine.connect() as connection:
            columns = {column["name"]: column for column in inspect(connection).get_columns("prop_books")}
            for name in ("provider_bookmaker_key", "provider_title", "provider_observed_at", "ingested_at"):
                self.assertTrue(columns[name]["nullable"])
        with self.Session() as session:
            offer = session.get(PropBook, ids["offer"])
            self.assertEqual((offer.line, offer.over_odds, offer.under_odds), (1.5, -110, 120))
            self.assertEqual((offer.updated_at, offer.ingested_at), (old_write, old_write))
            self.assertIsNone(offer.provider_observed_at)
            self.assertIsNone(offer.provider_bookmaker_key)
            self.assertIsNone(offer.provider_title)
            self.assert_selection_preserved(session, ids)
            self.assertIsNotNone(session.get(User, ids["user"]))
            self.assertIsNotNone(session.get(Slip, ids["slip"]))
            self.assertEqual(session.query(PropBookSnapshot).count(), 1)

        with self.isolated_api(ids["user"]) as client:
            research = client.get("/players/" + ids["player"] + "/research")
            self.assertEqual(research.status_code, 200, research.text)
            self.assertEqual(research.json()["available_props"], [])
            saved = client.get("/users/me/saved")
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["saved"][0]["id"], ids["prop"])
            slip = client.get("/users/me/slip")
            self.assertEqual(slip.status_code, 200, slip.text)
            self.assertFalse(slip.json()["slip"]["items"][0]["selection"]["actionable"])

    def test_real_constraint_failure_rolls_back_one_sport_while_next_sport_commits(self):
        ids = self.seed_selection()
        statuses = {key: make_sport_status(key) for key in ("baseball_mlb", "basketball_nba")}
        for status in statuses.values():
            status["active"] = True
        first, second = self.Session(), self.Session()

        @event.listens_for(first, "before_commit", once=True)
        def violate_current_offer_uniqueness(session):
            # A real PostgreSQL unique violation aborts this entire transaction.
            session.add(PropBook(prop_id=ids["prop"], sportsbook="FanDuel", line=99.5))

        nba_row = self.row()
        nba_row.update(player_name="NBA Test Player", prop_type="points", event_id="nba-event")
        with patch.object(fetch_odds, "SPORT_CONFIG", {key: fetch_odds.SPORT_CONFIG[key] for key in statuses}), \
                patch.object(fetch_odds, "SessionLocal", side_effect=[first, second]):
            fetch_odds.persist_sports(statuses, {"baseball_mlb": [self.row()], "basketball_nba": [nba_row]},
                {"basketball_nba": {"nba test player": {"team": nba_row["home_team"], "team_abbr": "HOM",
                                                        "provider_player_id": "isolated-nba-athlete"}}})
        self.assertEqual(statuses["baseball_mlb"]["outcome"], "failed")
        self.assertIn("IntegrityError", statuses["baseball_mlb"]["error_category"])
        self.assertEqual(statuses["baseball_mlb"]["sportsbook_offers_saved"], 0)
        self.assertEqual(statuses["basketball_nba"]["outcome"], "completed")
        with self.Session() as session:
            self.assertEqual(session.get(PropBook, ids["offer"]).line, 1.5)
            self.assertEqual(session.query(Prop).filter_by(odds_event_id="nba-event").count(), 1)
            self.assertEqual(session.query(PropBookSnapshot).filter_by(prop_id=ids["prop"]).count(), 1)
            self.assert_selection_preserved(session, ids)

    def test_classifier_uses_read_only_transaction_and_postgres_rejects_zero_row_write(self):
        from app.services.event_backfill import read_prop_identities

        ids = self.seed_selection()
        observed = []

        def verify_classifier_connection(connection, cursor, statement, parameters, context, executemany):
            if "SELECT p.id AS prop_id" not in statement:
                return
            # Inspect and challenge the actual inventory connection/transaction,
            # not a separate connection that happens to use read-only mode.
            observed.append(connection.exec_driver_sql("SHOW transaction_read_only").scalar_one())
            self.assertEqual(connection.exec_driver_sql("SHOW transaction_isolation").scalar_one(), "repeatable read")
            savepoint = connection.begin_nested()
            try:
                with self.assertRaises(DBAPIError) as failure:
                    connection.exec_driver_sql("UPDATE props SET is_active = is_active WHERE false")
                original = failure.exception.orig
                self.assertEqual(getattr(original, "pgcode", None) or getattr(original, "sqlstate", None), "25006")
            finally:
                # Recover from PostgreSQL's aborted statement so inventory SELECT
                # can finish inside the same protected outer transaction.
                savepoint.rollback()

        event.listen(self.engine, "before_cursor_execute", verify_classifier_connection)
        try:
            rows = read_prop_identities(self.engine)
        finally:
            event.remove(self.engine, "before_cursor_execute", verify_classifier_connection)
        self.assertEqual(observed, ["on"])
        self.assertEqual([str(row["prop_id"]) for row in rows], [ids["prop"]])
        with self.Session() as session:
            self.assertEqual(session.get(Prop, ids["prop"]).line, 1.5)
            self.assert_selection_preserved(session, ids)

    def test_postgres_nba_research_uses_prior_season_logs_without_populating_current_season(self):
        from app.services.game_log_fields import provider_season

        Base.metadata.drop_all(self.engine)
        self.upgrade_isolated_schema()
        ids = self.seed_selection()
        with self.Session.begin() as session:
            player, prop = session.get(Player, ids["player"]), session.get(Prop, ids["prop"])
            player.sport = "NBA"
            prop.prop_type, prop.line = "points", 20.5
            prop.odds_sport_key = "basketball_nba"
            offer = session.get(PropBook, ids["offer"])
            offer.line = 20.5
            selected_season = provider_season("NBA", prop.game_time)
            history_start = datetime(selected_season - 1, 3, 1, 19)
            for index in range(12):
                session.add(PlayerGameLog(player_id=player.id, sport="NBA",
                    external_game_id="isolated-espn-" + str(index),
                    game_date=history_start + timedelta(days=index), opponent="Away Team", is_home=True,
                    stats={"points": 25 if index >= 7 else 10, "minutes": 30}, source="espn_nba"))
        with self.isolated_api(ids["user"]) as client:
            response = client.get("/players/" + ids["player"] + "/research?prop_type=points&line=20.5")
            self.assertEqual(response.status_code, 200, response.text)
            research = response.json()
            self.assertEqual(research["selected_prop"]["id"], ids["prop"])
            self.assertEqual(len(research["available_props"]), 1)
            self.assertEqual(research["history"]["stored_games"], 12)
            self.assertEqual(research["history"]["eligible_games"], 12)
            self.assertEqual(research["history"]["current_season_games"], 0)
            self.assertEqual(research["history"]["previous_season_games"], 12)
            self.assertEqual(research["trends"]["l5"]["games"], 5)
            self.assertEqual(research["trends"]["l5"]["hit_rate"], 1.0)
            self.assertEqual(research["trends"]["l10"]["games"], 10)
            self.assertEqual(research["trends"]["l10"]["hit_rate"], 0.5)
            self.assertEqual(research["trends"]["l5"]["season_scope"], "previous_seasons")
            self.assertEqual(research["trends"]["season_window"]["games"], 0)
            self.assertIsNone(research["trends"]["season_window"]["hit_rate"])
        with self.Session() as session:
            self.assertEqual(session.query(PlayerGameLog).count(), 12)
            self.assert_selection_preserved(session, ids)

    def isolated_api(self, user_id):
        # Explicit isolated app: no production startup, scheduler, or provider client.
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.auth import get_current_user, get_optional_user
        from app.database import get_db
        from app.routers.props import router as props_router
        from app.routers.users import user_router

        app = FastAPI()
        from app.routers.players import router as players_router

        app.include_router(props_router, prefix="/props")
        app.include_router(players_router, prefix="/players")
        app.include_router(user_router, prefix="/users")

        def isolated_session():
            with self.Session() as session:
                yield session

        def isolated_user():
            with self.Session() as session:
                user = session.get(User, user_id)
                session.expunge(user)
                return user

        app.dependency_overrides[get_db] = isolated_session
        app.dependency_overrides[get_current_user] = isolated_user
        app.dependency_overrides[get_optional_user] = isolated_user
        return TestClient(app)

    def seed_second_independent_pick(self, first_ids):
        with self.Session.begin() as session:
            first = session.get(Prop, first_ids["prop"])
            prop = Prop(player_id=first.player_id, prop_type="runs", line=0.5,
                        sportsbook="FanDuel", odds_event_id="independent-event",
                        odds_sport_key="baseball_mlb", game_time=self.now + timedelta(hours=4),
                        opponent="Away Team", is_active=True)
            session.add(prop)
            session.flush()
            session.add(PropBook(prop_id=prop.id, sportsbook="FanDuel", line=0.5,
                                 over_odds=120, under_odds=-130, provider_bookmaker_key="fanduel",
                                 provider_title="FanDuel", provider_observed_at=self.now,
                                 ingested_at=self.now, updated_at=self.now))
            return prop.id

    def test_isolated_research_saved_slip_and_payout_routes_accept_observed_offers(self):
        Base.metadata.drop_all(self.engine)
        self.upgrade_isolated_schema()
        ids = self.seed_selection()
        second = self.seed_second_independent_pick(ids)
        with self.isolated_api(ids["user"]) as client:
            feed = client.get("/props/feed?sport=MLB")
            self.assertEqual(feed.status_code, 200, feed.text)
            self.assertEqual({row["id"] for row in feed.json()["props"]}, {ids["prop"], second})
            saved = client.get("/users/me/saved")
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["saved"][0]["id"], ids["prop"])
            slip = client.get("/users/me/slip")
            self.assertEqual(slip.status_code, 200, slip.text)
            self.assertTrue(slip.json()["slip"]["items"][0]["selection"]["actionable"])
            estimate = client.post("/users/me/slip/estimate", json={"items": [
                {"prop_id": ids["prop"], "sportsbook": "FanDuel", "line": 1.5, "side": "over"},
                {"prop_id": second, "sportsbook": "FanDuel", "line": 0.5, "side": "over"}]})
            self.assertEqual(estimate.status_code, 200, estimate.text)
            self.assertEqual(estimate.json()["method"], "independent")
            self.assertGreater(estimate.json()["decimal"], 1)
            research = client.get("/players/" + ids["player"] + "/research?prop_type=hits")
            self.assertEqual(research.status_code, 200, research.text)
            self.assertEqual(research.json()["selected_prop"]["id"], ids["prop"])
            self.assertEqual(research.json()["games"], [])  # Missing history is not fabricated.

    def test_expired_research_offer_remains_saved_and_in_slip_but_payout_is_unavailable(self):
        Base.metadata.drop_all(self.engine)
        self.upgrade_isolated_schema()
        ids = self.seed_selection()
        second = self.seed_second_independent_pick(ids)
        with self.Session.begin() as session:
            session.get(PropBook, ids["offer"]).provider_observed_at = self.now - timedelta(hours=7)
        with self.isolated_api(ids["user"]) as client:
            feed = client.get("/props/feed?sport=MLB")
            self.assertEqual(feed.status_code, 200, feed.text)
            self.assertNotIn(ids["prop"], {row["id"] for row in feed.json()["props"]})
            saved = client.get("/users/me/saved")
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["saved"][0]["id"], ids["prop"])
            slip = client.get("/users/me/slip")
            self.assertEqual(slip.status_code, 200, slip.text)
            item = slip.json()["slip"]["items"][0]
            self.assertEqual((item["prop_id"], item["side"], item["selection"]["sportsbook"], item["selection"]["line"]),
                             (ids["prop"], "over", "FanDuel", 1.5))
            self.assertFalse(item["selection"]["actionable"])
            estimate = client.post("/users/me/slip/estimate", json={"items": [
                {"prop_id": ids["prop"], "sportsbook": "FanDuel", "line": 1.5, "side": "over"},
                {"prop_id": second, "sportsbook": "FanDuel", "line": 0.5, "side": "over"}]})
            self.assertEqual(estimate.status_code, 200, estimate.text)
            self.assertEqual(estimate.json()["method"], "unavailable")
            self.assertIsNone(estimate.json()["decimal"])
            research = client.get("/players/" + ids["player"] + "/research")
            self.assertEqual(research.status_code, 200, research.text)
            self.assertNotIn(ids["prop"], {row["id"] for row in research.json()["available_props"]})


if __name__ == "__main__":
    unittest.main()
