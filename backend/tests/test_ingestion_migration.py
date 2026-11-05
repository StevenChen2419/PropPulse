"""Isolated migration checks; these do not prove PostgreSQL DDL semantics."""

import importlib.util
from pathlib import Path
import unittest

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


BACKEND = Path(__file__).resolve().parents[1]
REVISION_PATH = BACKEND / "alembic" / "versions" / "20261014_01_offer_provenance.py"
spec = importlib.util.spec_from_file_location("offer_provenance_revision", REVISION_PATH)
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)


class IngestionMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE prop_books (id VARCHAR PRIMARY KEY, sportsbook VARCHAR, "
                "line FLOAT, over_odds INTEGER, under_odds INTEGER, updated_at DATETIME)"
            ))
            connection.execute(text(
                "INSERT INTO prop_books VALUES "
                "('offer', 'Legacy Book', 12.5, -110, NULL, '2026-10-13 09:00:00')"
            ))
            for table in ("prop_book_snapshots", "saved_props", "slip_items"):
                connection.execute(text(f"CREATE TABLE {table} (id VARCHAR PRIMARY KEY)"))
                connection.execute(text(f"INSERT INTO {table} VALUES ('preserved')"))

    def upgrade_directly(self, connection):
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()

    def test_additive_backfill_preserves_records_and_does_not_invent_provider_data(self):
        with self.engine.begin() as connection:
            self.upgrade_directly(connection)
            row = connection.execute(text("SELECT * FROM prop_books")).mappings().one()
            self.assertEqual(row["updated_at"], "2026-10-13 09:00:00")
            self.assertEqual(row["ingested_at"], row["updated_at"])
            self.assertIsNone(row["provider_observed_at"])
            self.assertIsNone(row["provider_bookmaker_key"])
            self.assertIsNone(row["provider_title"])
            self.assertEqual((row["id"], row["sportsbook"], row["line"], row["over_odds"], row["under_odds"]),
                             ("offer", "Legacy Book", 12.5, -110, None))
            columns = {column["name"]: column for column in inspect(connection).get_columns("prop_books")}
            for name in ("provider_observed_at", "ingested_at", "provider_bookmaker_key", "provider_title"):
                self.assertTrue(columns[name]["nullable"])
            for table in ("prop_book_snapshots", "saved_props", "slip_items"):
                self.assertEqual(connection.execute(text(f"SELECT id FROM {table}")).scalar_one(), "preserved")

    def test_repeated_revision_does_not_overwrite_known_provenance(self):
        with self.engine.begin() as connection:
            self.upgrade_directly(connection)
            connection.execute(text(
                "UPDATE prop_books SET provider_bookmaker_key = 'stable', provider_title = 'New Title', "
                "provider_observed_at = '2026-10-13 08:00:00', ingested_at = '2026-10-13 10:00:00'"
            ))
            before = connection.execute(text("SELECT * FROM prop_books")).one()
            self.upgrade_directly(connection)
            self.assertEqual(connection.execute(text("SELECT * FROM prop_books")).one(), before)

    def test_alembic_upgrade_records_revision_and_second_upgrade_is_noop(self):
        config = Config(str(BACKEND / "alembic.ini"))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            # This deliberately minimal SQLite fixture tests revision 01 only.
            # Complete head migrations/constraints are covered on PostgreSQL.
            command.upgrade(config, "20261014_01")
            self.assertEqual(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
                             "20261014_01")
            before = connection.execute(text("SELECT * FROM prop_books")).one()
            command.upgrade(config, "20261014_01")
            self.assertEqual(connection.execute(text("SELECT * FROM prop_books")).one(), before)

    def test_partial_database_without_offer_table_is_refused(self):
        isolated = create_engine("sqlite://")
        try:
            with isolated.begin() as connection:
                connection.execute(text("CREATE TABLE saved_props (id VARCHAR)"))
                with self.assertRaisesRegex(RuntimeError, "nonempty database"):
                    self.upgrade_directly(connection)
                self.assertEqual(inspect(connection).get_table_names(), ["saved_props"])
        finally:
            isolated.dispose()

    def test_downgrade_refuses_data_loss(self):
        with self.assertRaisesRegex(RuntimeError, "discard offer provenance"):
            revision.downgrade()


if __name__ == "__main__":
    unittest.main()
