"""Opt-in Event migration checks on disposable PostgreSQL UUID test schemas only."""
from datetime import datetime, timedelta
import importlib.util
import os
from pathlib import Path
import unittest
import uuid

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, create_engine, event, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.database import Base
from app import models  # register metadata, without application startup

TEST_URL = os.environ.get("PROPPULSE_TEST_POSTGRES_URL")
BACKEND = Path(__file__).resolve().parents[1]


@unittest.skipUnless(TEST_URL, "Explicit disposable PostgreSQL test URL is unset; no connection attempted")
class EventMigrationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            target = make_url(TEST_URL)
        except Exception:
            raise RuntimeError("Invalid explicit PostgreSQL test URL") from None
        if (target.get_backend_name() != "postgresql" or not target.database
                or not target.database.startswith("proppulse_test_")):
            raise RuntimeError("Event tests require an explicit proppulse_test_ database")
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
        def isolated_path(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute('SET search_path TO "' + self.schema + '"')
                dbapi_connection.commit()
            finally:
                cursor.close()

    def remove_schema(self):
        if not self.schema.startswith("proppulse_test_") or len(self.schema) != len("proppulse_test_") + 32:
            raise RuntimeError("Unexpected schema cleanup target")
        with self.admin.begin() as connection:
            connection.execute(DropSchema(self.schema, cascade=True))

    def upgrade(self, target="head"):
        config = Config(str(BACKEND / "alembic.ini"))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, target)

    def revision(self):
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    def legacy_schema(self):
        """Remove only the additive Phase 3B objects to represent pre-3B metadata."""
        legacy = MetaData()
        for table in Base.metadata.sorted_tables:
            table.to_metadata(legacy)
        props = legacy.tables["props"]
        if "event_id" in props.c:
            column = props.c.event_id
            for constraint in list(props.constraints):
                if any(member is column for member in getattr(constraint, "columns", ())):
                    props.constraints.remove(constraint)
            props.foreign_keys.difference_update(column.foreign_keys)
            for index in list(props.indexes):
                if "event_id" in index.columns:
                    props.indexes.remove(index)
            props._columns.remove(column)
        if "events" in legacy.tables:
            legacy.remove(legacy.tables["events"])
        if "nba_evidence_records" in legacy.tables:
            legacy.remove(legacy.tables["nba_evidence_records"])
        legacy.create_all(self.engine)
        self.upgrade("20261014_01")
        return legacy

    def legacy_records(self, legacy):
        ids = {key: str(uuid.uuid4()) for key in ("player", "user", "prop", "missing", "ambiguous", "book", "snapshot", "log", "slip", "item", "saved", "interaction", "fatigue", "ranking")}
        now = datetime(2026, 10, 14, 17)
        with self.engine.begin() as connection:
            def add(table, **values):
                connection.execute(legacy.tables[table].insert().values(**values))
            add("players", id=ids["player"], name="Retained Player", team="Mutable Team", team_abbr="MUT", sport="NBA")
            add("users", id=ids["user"], email="isolated@example.invalid", hashed_password="test-only",
                fav_players=[ids["player"]], fav_sports=["NBA"], fav_prop_types=["points"])
            for key, provider_id in (("prop", "provider-event"), ("missing", None), ("ambiguous", "provider-event")):
                add("props", id=ids[key], player_id=ids["player"], prop_type="points", line=20.5,
                    odds_event_id=provider_id, odds_sport_key="basketball_nba", game_time=now + timedelta(days=1),
                    opponent="Unverified Opponent" if key != "ambiguous" else "Conflicting Opponent")
            add("prop_books", id=ids["book"], prop_id=ids["prop"], sportsbook="FanDuel", line=20.5,
                over_odds=-110, under_odds=120, provider_bookmaker_key="fanduel", provider_title="FanDuel",
                provider_observed_at=now, ingested_at=now)
            add("prop_book_snapshots", id=ids["snapshot"], prop_id=ids["prop"], sportsbook="FanDuel", line=19.5, over_odds=-110)
            add("player_game_logs", id=ids["log"], player_id=ids["player"], sport="NBA", external_game_id="espn-history",
                game_date=now - timedelta(days=200), stats={"points": 25, "minutes": 30}, source="espn_nba")
            add("slips", id=ids["slip"], user_id=ids["user"])
            add("slip_items", id=ids["item"], slip_id=ids["slip"], prop_id=ids["prop"], sportsbook="FanDuel", line=20.5, side="under")
            add("saved_props", id=ids["saved"], user_id=ids["user"], prop_id=ids["prop"])
            add("interactions", id=ids["interaction"], user_id=ids["user"], prop_id=ids["prop"], action="save")
            add("fatigue_scores", id=ids["fatigue"], player_id=ids["player"])
            add("rankings", id=ids["ranking"], prop_id=ids["prop"], user_id=ids["user"])
        return ids

    def snapshot(self, metadata):
        with self.engine.connect() as connection:
            return {table.name: [dict(row) for row in connection.execute(select(table).order_by(table.c.id)).mappings()]
                    for table in metadata.sorted_tables}

    def event_values(self, **changes):
        return {"id": str(uuid.uuid4()), "provider": "the_odds_api", "provider_event_id": "event-one",
                "sport_key": "basketball_nba", "home_team": "Home Team", "away_team": "Away Team",
                "scheduled_start_at": datetime(2026, 10, 20, 19), "updated_at": datetime(2026, 10, 14, 17), **changes}

    def insert_event(self, connection, **changes):
        values = self.event_values(**changes)
        connection.execute(text("INSERT INTO events (id,provider,provider_event_id,sport_key,home_team,away_team,scheduled_start_at,updated_at) "
                                "VALUES (:id,:provider,:provider_event_id,:sport_key,:home_team,:away_team,:scheduled_start_at,:updated_at)"), values)
        return values["id"]

    def test_fresh_bootstrap_is_complete_and_repeated_head_has_no_metadata_diffs(self):
        self.upgrade()
        self.assertEqual(self.revision(), "20261022_05")
        self.upgrade()
        with self.engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            self.assertEqual(compare_metadata(context, Base.metadata), [])
            self.assertEqual(connection.execute(text("SELECT count(*) FROM events")).scalar_one(), 0)

    def test_legacy_upgrade_preserves_every_row_and_leaves_all_links_unresolved(self):
        legacy = self.legacy_schema()
        self.legacy_records(legacy)
        before = self.snapshot(legacy)
        self.upgrade()
        self.upgrade()
        self.assertEqual(self.snapshot(legacy), before)
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT count(*) FROM events")).scalar_one(), 0)
            self.assertEqual(connection.execute(text("SELECT count(*) FROM props WHERE event_id IS NULL")).scalar_one(), 3)

    def test_one_sided_schema_refused_without_replacing_or_repairing_objects(self):
        legacy = self.legacy_schema()
        self.legacy_records(legacy)
        before = self.snapshot(legacy)
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE events (id UUID PRIMARY KEY)"))
        with self.assertRaisesRegex(RuntimeError, "only one"):
            self.upgrade()
        self.assertEqual(self.revision(), "20261014_01")
        self.assertEqual(self.snapshot(legacy), before)
        with self.engine.connect() as connection:
            self.assertEqual([column["name"] for column in inspect(connection).get_columns("events")], ["id"])
            self.assertNotIn("event_id", {column["name"] for column in inspect(connection).get_columns("props")})

    def test_missing_baseline_column_refused_before_any_new_ddl(self):
        self.legacy_schema()
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE players DROP COLUMN jersey_number"))
        with self.assertRaisesRegex(RuntimeError, "baseline columns"):
            self.upgrade()
        with self.engine.connect() as connection:
            self.assertNotIn("events", inspect(connection).get_table_names())
        self.assertEqual(self.revision(), "20261014_01")

    def test_precreated_schema_with_missing_index_is_refused_without_repair(self):
        Base.metadata.create_all(self.engine)
        self.upgrade("20261014_01")
        with self.engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_props_event_id"))
        with self.assertRaisesRegex(RuntimeError, "ix_props_event_id"):
            self.upgrade()
        self.assertEqual(self.revision(), "20261014_01")
        with self.engine.connect() as connection:
            self.assertNotIn("ix_props_event_id", {item["name"] for item in inspect(connection).get_indexes("props")})

    def test_precreated_schema_with_wrong_named_check_is_refused(self):
        Base.metadata.create_all(self.engine)
        self.upgrade("20261014_01")
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE events DROP CONSTRAINT ck_events_distinct_teams"))
            connection.execute(text("ALTER TABLE events ADD CONSTRAINT ck_events_distinct_teams CHECK (true)"))
        with self.assertRaisesRegex(RuntimeError, "ck_events_distinct_teams"):
            self.upgrade()
        self.assertEqual(self.revision(), "20261014_01")

    def test_precreated_schema_missing_foreign_key_is_refused_without_repair(self):
        Base.metadata.create_all(self.engine)
        self.upgrade("20261014_01")
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE props DROP CONSTRAINT fk_props_event_id_events"))
        with self.assertRaisesRegex(RuntimeError, "foreign key"):
            self.upgrade()
        self.assertEqual(self.revision(), "20261014_01")
        with self.engine.connect() as connection:
            self.assertFalse(any("event_id" in link["constrained_columns"] for link in inspect(connection).get_foreign_keys("props")))

    def test_precreated_schema_missing_check_is_refused_without_repair(self):
        Base.metadata.create_all(self.engine)
        self.upgrade("20261014_01")
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE events DROP CONSTRAINT ck_events_nonempty_identity"))
        with self.assertRaisesRegex(RuntimeError, "ck_events_nonempty_identity"):
            self.upgrade()
        self.assertEqual(self.revision(), "20261014_01")
        with self.engine.connect() as connection:
            self.assertNotIn("ck_events_nonempty_identity", {check["name"] for check in inspect(connection).get_check_constraints("events")})

    def test_direct_revision_revalidation_preserves_guard_objects_and_event_data(self):
        self.upgrade()
        with self.engine.begin() as connection:
            identifier = self.insert_event(connection)
            before = connection.execute(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                                             "WHERE n.nspname=current_schema() AND p.proname='guard_prop_event_identity'")).scalar_one()
            path = BACKEND / "alembic" / "versions" / "20261014_02_event_identity.py"
            spec = importlib.util.spec_from_file_location("event_identity_revision_test", path)
            revision = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(revision)
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade()
            after = connection.execute(text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                                            "WHERE n.nspname=current_schema() AND p.proname='guard_prop_event_identity'")).scalar_one()
            self.assertEqual(after, before)
            self.assertEqual(str(connection.execute(text("SELECT id FROM events")).scalar_one()), identifier)

    def test_conflicting_existing_guard_definition_is_refused_without_replacement(self):
        Base.metadata.create_all(self.engine)
        self.upgrade("20261014_01")
        with self.engine.begin() as connection:
            connection.execute(text("CREATE FUNCTION guard_prop_event_identity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$"))
            connection.execute(text("CREATE TRIGGER trg_props_event_identity BEFORE UPDATE OF event_id ON props FOR EACH ROW EXECUTE FUNCTION guard_prop_event_identity()"))
        with self.assertRaisesRegex(RuntimeError, "guard definition"):
            self.upgrade()
        self.assertEqual(self.revision(), "20261014_01")
        with self.engine.connect() as connection:
            source = connection.execute(text("SELECT p.prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                                             "WHERE n.nspname=current_schema() AND p.proname='guard_prop_event_identity'")).scalar_one()
            self.assertEqual(source.strip(), "BEGIN RETURN NEW; END;")

    def test_unique_identity_is_namespaced_by_provider_and_sport(self):
        self.upgrade()
        with self.engine.begin() as connection:
            self.insert_event(connection)
            with self.assertRaises(IntegrityError):
                with connection.begin_nested():
                    self.insert_event(connection)
            self.insert_event(connection, sport_key="icehockey_nhl")
            self.insert_event(connection, provider="another_verified_provider")
            self.assertEqual(connection.execute(text("SELECT count(*) FROM events")).scalar_one(), 3)

    def test_database_rejects_blank_identity_missing_fields_and_same_teams(self):
        self.upgrade()
        with self.engine.begin() as connection:
            for changes in ({"provider": " "}, {"provider_event_id": " "}, {"sport_key": " "},
                            {"home_team": " "}, {"away_team": " "}, {"home_team": " away TEAM "},
                            {"scheduled_start_at": None}, {"updated_at": None}):
                with self.subTest(changes=changes):
                    with self.assertRaises(IntegrityError):
                        with connection.begin_nested():
                            self.insert_event(connection, **changes)

    def test_link_foreign_key_delete_restriction_and_direct_sql_reassignment_guard(self):
        legacy = self.legacy_schema()
        ids = self.legacy_records(legacy)
        self.upgrade()
        with self.engine.begin() as connection:
            first = self.insert_event(connection)
            second = self.insert_event(connection, provider_event_id="event-two")
            with self.assertRaises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(text("UPDATE props SET event_id = :event WHERE id = :id"), {"event": str(uuid.uuid4()), "id": ids["prop"]})
            connection.execute(text("UPDATE props SET event_id = :event WHERE id = :id"), {"event": first, "id": ids["prop"]})
            connection.execute(text("UPDATE props SET event_id = :event WHERE id = :id"), {"event": first, "id": ids["prop"]})
            for replacement in (second, None):
                with self.assertRaises(IntegrityError) as failure:
                    with connection.begin_nested():
                        connection.execute(text("UPDATE props SET event_id = :event WHERE id = :id"), {"event": replacement, "id": ids["prop"]})
                self.assertEqual(failure.exception.orig.pgcode, "23514")
            with self.assertRaises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(text("DELETE FROM events WHERE id = :id"), {"id": first})
            connection.execute(text("UPDATE events SET scheduled_start_at = :start WHERE id = :id"),
                               {"start": datetime(2026, 10, 21, 19), "id": first})
            self.assertEqual(str(connection.execute(text("SELECT event_id FROM props WHERE id = :id"), {"id": ids["prop"]}).scalar_one()), first)

    def test_conflicting_guard_causes_transactional_rollback_of_new_event_schema(self):
        legacy = self.legacy_schema()
        self.legacy_records(legacy)
        before = self.snapshot(legacy)
        with self.engine.begin() as connection:
            connection.execute(text("CREATE FUNCTION guard_prop_event_identity() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$"))
        with self.assertRaisesRegex(RuntimeError, "guard"):
            self.upgrade()
        self.assertEqual(self.revision(), "20261014_01")
        self.assertEqual(self.snapshot(legacy), before)
        with self.engine.connect() as connection:
            self.assertNotIn("events", inspect(connection).get_table_names())
            self.assertNotIn("event_id", {column["name"] for column in inspect(connection).get_columns("props")})

    def test_downgrade_refuses_data_loss_and_preserves_revision(self):
        self.upgrade()
        config = Config(str(BACKEND / "alembic.ini"))
        with self.assertRaisesRegex(RuntimeError, "invalidate retained NBA.com evidence"):
            with self.engine.begin() as connection:
                config.attributes["connection"] = connection
                command.downgrade(config, "20261014_01")
        self.assertEqual(self.revision(), "20261022_05")


if __name__ == "__main__":
    unittest.main()
