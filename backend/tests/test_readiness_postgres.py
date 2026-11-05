"""Real readiness against randomly named disposable PostgreSQL schemas."""
import os
import unittest
from unittest.mock import patch
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from uuid import uuid4
from app.services.readiness_service import check_readiness
from test_security_hardening import production
import test_event_migration_postgres as migration_fixture


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit disposable PostgreSQL URL required")
class SecurityReadinessPostgresTests(unittest.TestCase):
    def setUp(self):
        cls = migration_fixture.EventMigrationPostgresTests
        cls.setUpClass()
        self.fixture = cls("test_fresh_bootstrap_is_complete_and_repeated_head_has_no_metadata_diffs")
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.engine = self.fixture.engine
        self.fixture.upgrade()

    def result(self):
        return check_readiness(self.engine, production())

    def test_ready_read_only_no_schema_or_data_writes(self):
        statements = []
        def observe(conn, cursor, statement, *args):
            statements.append(statement.strip().split()[0].upper())
        event.listen(self.engine, "before_cursor_execute", observe)
        self.assertEqual(self.result(), {"status": "ready"})
        self.assertFalse(set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"})
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SHOW transaction_read_only")).scalar(), "off")

    def test_wrong_revision(self):
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num='wrong'"))
        self.assertEqual(self.result()["reason"], "schema_revision")

    def test_missing_revision(self):
        with self.engine.begin() as conn:
            conn.execute(text("DROP TABLE alembic_version"))
        self.assertEqual(self.result()["reason"], "schema_revision")

    def test_missing_trigger_and_recovery(self):
        with self.engine.begin() as conn:
            conn.execute(text("DROP TRIGGER trg_props_event_identity ON props"))
        self.assertEqual(self.result()["reason"], "schema_prerequisites")
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TRIGGER trg_props_event_identity BEFORE UPDATE OF event_id ON props "
                              "FOR EACH ROW EXECUTE FUNCTION guard_prop_event_identity()"))
        self.assertEqual(self.result(), {"status": "ready"})

    def test_disabled_trigger(self):
        with self.engine.begin() as conn:
            conn.execute(text("ALTER TABLE props DISABLE TRIGGER trg_props_event_identity"))
        self.assertEqual(self.result()["reason"], "schema_prerequisites")

    def test_replaced_trigger_function(self):
        with self.engine.begin() as conn:
            conn.execute(text("CREATE OR REPLACE FUNCTION guard_prop_event_identity() RETURNS trigger "
                              "LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$"))
        self.assertEqual(self.result()["reason"], "schema_prerequisites")

    def test_missing_critical_constraint(self):
        with self.engine.begin() as conn:
            conn.execute(text("ALTER TABLE prop_books DROP CONSTRAINT uq_prop_books_prop_sportsbook"))
        self.assertEqual(self.result()["reason"], "schema_prerequisites")

    def test_missing_unique_email_index(self):
        with self.engine.begin() as conn:
            conn.execute(text("DROP INDEX ix_users_email"))
        self.assertEqual(self.result()["reason"], "schema_prerequisites")

    def test_failed_concurrent_unique_index_rebuild_rejected(self):
        with self.engine.begin() as conn:
            conn.execute(text("DROP INDEX ix_users_email"))
            for _ in range(2):
                conn.execute(text("INSERT INTO users (id,email,hashed_password) VALUES (:id,:email,:password)"),
                             {"id": str(uuid4()), "email": "duplicate@example.com", "password": "unused-fixture"})
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            with self.assertRaises(IntegrityError):
                conn.execute(text("CREATE UNIQUE INDEX CONCURRENTLY ix_users_email ON users (email)"))
            state = conn.execute(text("SELECT i.indisvalid, i.indisready FROM pg_index i "
                "JOIN pg_class r ON r.oid=i.indexrelid JOIN pg_namespace n ON n.oid=r.relnamespace "
                "WHERE n.nspname=current_schema() AND r.relname='ix_users_email'")).one()
            self.assertEqual(tuple(state), (False, False))
        self.assertEqual(self.result()["reason"], "schema_prerequisites")
        with self.engine.begin() as conn:
            conn.execute(text("ALTER INDEX ix_users_email RENAME TO renamed_failed_email_index"))
        self.assertEqual(self.result()["reason"], "schema_prerequisites")

    def test_unvalidated_event_check_rejected(self):
        with self.engine.begin() as conn:
            conn.execute(text("ALTER TABLE events DROP CONSTRAINT ck_events_distinct_teams"))
            conn.execute(text("ALTER TABLE events ADD CONSTRAINT ck_events_distinct_teams "
                              "CHECK (lower(trim(home_team)) != lower(trim(away_team))) NOT VALID"))
        self.assertEqual(self.result()["reason"], "schema_prerequisites")

    def test_unvalidated_event_foreign_key_rejected(self):
        with self.engine.begin() as conn:
            conn.execute(text("ALTER TABLE props DROP CONSTRAINT fk_props_event_id_events"))
            conn.execute(text("ALTER TABLE props ADD CONSTRAINT fk_props_event_id_events "
                              "FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE RESTRICT NOT VALID"))
        self.assertEqual(self.result()["reason"], "schema_prerequisites")

    def test_real_connection_failure_and_recovery(self):
        from sqlalchemy import create_engine
        offline = create_engine("postgresql://fixture@127.0.0.1:1/proppulse_test_offline", connect_args={"connect_timeout": 1})
        self.addCleanup(offline.dispose)
        self.assertEqual(check_readiness(offline, production())["reason"], "database_unavailable")
        self.assertEqual(self.result(), {"status": "ready"})

    def test_production_lifespan_and_probes_without_writes_or_subprocesses(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import Base
        with patch("app.main.settings", production()), patch("app.main.engine", self.engine), \
             patch.object(Base.metadata, "create_all") as ddl, patch("app.main.LiveRefresh") as refresh:
            with TestClient(app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/ready").json(), {"status": "ready"})
                self.assertEqual(client.get("/__test__/manifest").status_code, 404)
            ddl.assert_not_called()
            refresh.return_value.start.assert_not_called()
