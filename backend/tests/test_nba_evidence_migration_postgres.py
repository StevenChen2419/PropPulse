"""Append-only evidence migration checks on explicit disposable PostgreSQL schemas."""
from datetime import datetime, timezone, timedelta
import importlib.util
import os
from pathlib import Path
import unittest
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.models import NBAEvidenceRecord
from app.services.readiness_service import check_readiness
from test_security_hardening import production
import test_event_migration_postgres as fixture_module


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit disposable PostgreSQL URL required")
class NBAEvidenceMigrationPostgresTests(unittest.TestCase):
    def setUp(self):
        cls = fixture_module.EventMigrationPostgresTests
        cls.setUpClass()
        self.fixture = cls()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.engine = self.fixture.engine

    def upgrade(self, target="head"):
        self.fixture.upgrade(target)

    def record(self, **changes):
        return {"id": str(uuid4()), "provider": "espn", "sport": "NBA", "kind": "game",
                "identity": "fixture-game", "payload": {"status": "completed"}, "source": "offline_fixture",
                "observed_at": datetime(2026, 10, 17, 10), "ingested_at": datetime(2026, 10, 17, 11),
                "fingerprint": "a" * 64, **changes}

    def insert(self, connection, **changes):
        row = self.record(**changes)
        connection.execute(NBAEvidenceRecord.__table__.insert().values(**row))
        return row

    def revision_module(self):
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20261017_03_nba_evidence.py"
        spec = importlib.util.spec_from_file_location("nba_evidence_revision_test", path)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        return revision

    def test_revision03_to_nba_namespace_preserves_observations_and_guards(self):
        self.upgrade("20261017_03")
        with self.engine.begin() as connection:
            self.insert(connection)
            before = connection.execute(text("SELECT * FROM nba_evidence_records")).mappings().all()
            guard = connection.execute(text("SELECT oid FROM pg_trigger WHERE tgrelid='nba_evidence_records'::regclass AND tgname='trg_nba_evidence_append_only'")).scalar_one()
        self.upgrade()
        with self.engine.begin() as connection:
            self.assertEqual(connection.execute(text("SELECT * FROM nba_evidence_records")).mappings().all(), before)
            self.assertEqual(connection.execute(text("SELECT oid FROM pg_trigger WHERE tgrelid='nba_evidence_records'::regclass AND tgname='trg_nba_evidence_append_only'")).scalar_one(), guard)
            self.insert(connection, provider="nba_com")
        self.assertEqual(check_readiness(self.engine, production()), {"status": "ready"})

    def test_revision03_is_not_ready_until_namespace_migration(self):
        self.upgrade("20261017_03")
        self.assertEqual(check_readiness(self.engine, production()), {"status": "not_ready", "reason": "schema_revision"})

    def test_direct_revision04_replay_keeps_constraint_and_guard_identities(self):
        self.upgrade()
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20261018_04_nba_com_namespace.py"
        spec = importlib.util.spec_from_file_location("nba_namespace_revision_test", path)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        with self.engine.begin() as connection:
            self.insert(connection, provider="nba_com")
            constraint = text("SELECT oid FROM pg_constraint WHERE conrelid='nba_evidence_records'::regclass AND conname='ck_nba_evidence_namespace'")
            guard = text("SELECT oid FROM pg_trigger WHERE tgrelid='nba_evidence_records'::regclass AND tgname='trg_nba_evidence_append_only'")
            before = (connection.execute(constraint).scalar_one(), connection.execute(guard).scalar_one())
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade()
                revision.upgrade()
            self.assertEqual((connection.execute(constraint).scalar_one(), connection.execute(guard).scalar_one()), before)
            self.assertEqual(connection.execute(text("SELECT count(*) FROM nba_evidence_records")).scalar_one(), 1)

    def test_revision04_refuses_missing_guard_without_repair_or_revision_advance(self):
        self.upgrade("20261017_03")
        with self.engine.begin() as connection:
            connection.execute(text("DROP TRIGGER trg_nba_evidence_append_only ON nba_evidence_records"))
        with self.assertRaisesRegex(RuntimeError, "missing evidence append-only guard"):
            self.upgrade()
        self.assertEqual(self.fixture.revision(), "20261017_03")
        with self.engine.connect() as connection:
            count = connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgrelid='nba_evidence_records'::regclass AND tgname='trg_nba_evidence_append_only'")).scalar_one()
            self.assertEqual(count, 0)

    def test_revision04_refuses_unreviewed_namespace_without_repair(self):
        self.upgrade("20261017_03")
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE nba_evidence_records DROP CONSTRAINT ck_nba_evidence_namespace"))
            connection.execute(text("ALTER TABLE nba_evidence_records ADD CONSTRAINT ck_nba_evidence_namespace CHECK (provider IN ('espn','other') AND sport='NBA')"))
        with self.assertRaisesRegex(RuntimeError, "ck_nba_evidence_namespace"):
            self.upgrade()
        self.assertEqual(self.fixture.revision(), "20261017_03")

    def test_revision02_upgrade_preserves_all_existing_rows_and_links(self):
        legacy = self.fixture.legacy_schema()
        ids = self.fixture.legacy_records(legacy)
        self.upgrade("20261014_02")
        with self.engine.begin() as connection:
            event_id = self.fixture.insert_event(connection)
            connection.execute(text("UPDATE props SET event_id=:event WHERE id=:id"), {"event": event_id, "id": ids["prop"]})
        old = MetaData()
        old.reflect(self.engine)
        old.remove(old.tables["alembic_version"])
        before = self.fixture.snapshot(old)
        self.upgrade()
        self.upgrade()
        after = self.fixture.snapshot(old)
        # Only the schema revision marker changes.
        self.assertEqual({key: value for key, value in after.items() if key != "alembic_version"},
                         {key: value for key, value in before.items() if key != "alembic_version"})
        self.assertEqual(self.fixture.revision(), "20261022_05")
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT count(*) FROM nba_evidence_records")).scalar_one(), 0)

    def test_existing_create_all_shape_adopted_without_changing_observations(self):
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            self.insert(connection)
        self.upgrade()
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT count(*) FROM nba_evidence_records")).scalar_one(), 1)
        self.assertEqual(check_readiness(self.engine, production()), {"status": "ready"})

    def test_repeated_direct_revision_validates_without_replacing_guard(self):
        self.upgrade()
        with self.engine.begin() as connection:
            self.insert(connection)
            query = text("SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=current_schema() AND p.proname='guard_nba_evidence_append_only'")
            before = connection.execute(query).scalar_one()
            with Operations.context(MigrationContext.configure(connection)):
                self.revision_module().upgrade()
            self.assertEqual(connection.execute(query).scalar_one(), before)
            self.assertEqual(connection.execute(text("SELECT count(*) FROM nba_evidence_records")).scalar_one(), 1)

    def test_partial_table_refused_without_repair_or_revision_advance(self):
        self.fixture.legacy_schema()
        self.upgrade("20261014_02")
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE nba_evidence_records (id UUID PRIMARY KEY)"))
        with self.assertRaisesRegex(RuntimeError, "unexpected evidence columns"):
            self.upgrade()
        self.assertEqual(self.fixture.revision(), "20261014_02")
        self.assertEqual([item["name"] for item in inspect(self.engine).get_columns("nba_evidence_records")], ["id"])

    def test_wrong_namespace_check_refused_without_repair(self):
        Base.metadata.create_all(self.engine)
        self.upgrade("20261014_02")
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE nba_evidence_records DROP CONSTRAINT ck_nba_evidence_namespace"))
            connection.execute(text("ALTER TABLE nba_evidence_records ADD CONSTRAINT ck_nba_evidence_namespace CHECK (provider='espn' AND sport='nba')"))
        with self.assertRaisesRegex(RuntimeError, "ck_nba_evidence_namespace"):
            self.upgrade()
        self.assertEqual(self.fixture.revision(), "20261014_02")

    def test_missing_index_refused_without_automatic_repair(self):
        Base.metadata.create_all(self.engine)
        self.upgrade("20261014_02")
        with self.engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_nba_evidence_records_team_id"))
        with self.assertRaisesRegex(RuntimeError, "ix_nba_evidence_records_team_id"):
            self.upgrade()
        self.assertEqual(self.fixture.revision(), "20261014_02")

    def test_conflicting_guard_rolls_back_new_table_and_revision(self):
        self.fixture.legacy_schema()
        self.upgrade("20261014_02")
        with self.engine.begin() as connection:
            connection.execute(text("CREATE FUNCTION guard_nba_evidence_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$"))
        with self.assertRaisesRegex(RuntimeError, "guard"):
            self.upgrade()
        self.assertEqual(self.fixture.revision(), "20261014_02")
        self.assertNotIn("nba_evidence_records", inspect(self.engine).get_table_names())

    def test_constraints_and_idempotent_identity_preserve_contradictions(self):
        self.upgrade()
        with self.engine.begin() as connection:
            self.insert(connection)
            with self.assertRaises(IntegrityError):
                with connection.begin_nested():
                    self.insert(connection)
            self.insert(connection, fingerprint="b" * 64, payload={"status": "unfinished"})
            self.assertEqual(connection.execute(text("SELECT count(*) FROM nba_evidence_records")).scalar_one(), 2)
            for changes in ({"provider": "other"}, {"sport": "WNBA"}, {"kind": "unknown"},
                            {"identity": " "}, {"source": " "}, {"fingerprint": "short"},
                            {"fingerprint": "C" * 64}, {"team_id": " "}, {"game_id": " "}, {"observed_at": None}):
                with self.subTest(changes=changes):
                    with self.assertRaises(IntegrityError):
                        with connection.begin_nested():
                            self.insert(connection, **changes)

    def test_database_refuses_update_delete_and_player_deletion(self):
        self.upgrade()
        player_id = str(uuid4())
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO players (id,name,team,team_abbr,sport) VALUES (:id,'Fixture','A','A','NBA')"), {"id": player_id})
            self.insert(connection, player_id=player_id)
            for sql in ("UPDATE nba_evidence_records SET source='changed'", "DELETE FROM nba_evidence_records", "DELETE FROM players"):
                with self.subTest(sql=sql):
                    with self.assertRaises(IntegrityError):
                        with connection.begin_nested():
                            connection.execute(text(sql))
            self.assertEqual(connection.execute(text("SELECT count(*) FROM nba_evidence_records")).scalar_one(), 1)

    def test_orm_refuses_mutation_and_normalizes_utc(self):
        self.upgrade()
        with Session(self.engine) as session:
            row = NBAEvidenceRecord(**self.record(observed_at=datetime(2026, 10, 17, 5, tzinfo=timezone(timedelta(hours=-5)))))
            self.assertEqual(row.observed_at, datetime(2026, 10, 17, 10))
            session.add(row)
            session.commit()
            row.source = "changed"
            with self.assertRaisesRegex(ValueError, "append-only"):
                session.flush()
            session.rollback()
            session.delete(row)
            with self.assertRaisesRegex(ValueError, "append-only"):
                session.flush()
            session.rollback()

    def test_missing_guard_not_ready_and_readiness_never_repairs(self):
        self.upgrade()
        with self.engine.begin() as connection:
            connection.execute(text("DROP TRIGGER trg_nba_evidence_append_only ON nba_evidence_records"))
        self.assertEqual(check_readiness(self.engine, production()), {"status": "not_ready", "reason": "schema_prerequisites"})
        with self.engine.connect() as connection:
            self.assertFalse(connection.execute(text("SELECT EXISTS(SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND t.tgname='trg_nba_evidence_append_only')")).scalar_one())

    def test_disabled_or_replaced_guard_not_ready(self):
        self.upgrade()
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE nba_evidence_records DISABLE TRIGGER trg_nba_evidence_append_only"))
        self.assertEqual(check_readiness(self.engine, production())["reason"], "schema_prerequisites")
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE nba_evidence_records ENABLE TRIGGER trg_nba_evidence_append_only"))
            connection.execute(text("CREATE OR REPLACE FUNCTION guard_nba_evidence_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$"))
        self.assertEqual(check_readiness(self.engine, production())["reason"], "schema_prerequisites")

    def test_missing_check_index_and_foreign_key_not_ready(self):
        self.upgrade()
        for sql in ("ALTER TABLE nba_evidence_records DROP CONSTRAINT ck_nba_evidence_nonempty",
                    "DROP INDEX ix_nba_evidence_records_game_id",
                    "ALTER TABLE nba_evidence_records DROP CONSTRAINT fk_nba_evidence_player_id_players"):
            with self.subTest(sql=sql):
                with self.engine.begin() as connection:
                    connection.execute(text(sql))
                self.assertEqual(check_readiness(self.engine, production())["reason"], "schema_prerequisites")

    def test_revision02_not_ready_under_new_application_contract(self):
        self.fixture.legacy_schema()
        self.upgrade("20261014_02")
        self.assertEqual(check_readiness(self.engine, production()), {"status": "not_ready", "reason": "schema_revision"})

    def test_downgrade_refused_without_losing_evidence(self):
        self.upgrade()
        with self.engine.begin() as connection:
            self.insert(connection)
            with Operations.context(MigrationContext.configure(connection)):
                with self.assertRaisesRegex(RuntimeError, "discard append-only"):
                    self.revision_module().downgrade()
        self.assertEqual(self.fixture.revision(), "20261022_05")
