import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from scripts.migrate_slip_selections import migrate


class SlipMigrationTests(unittest.TestCase):
    def test_adds_columns_and_pins_legacy_selection_only_once(self):
        engine = create_engine("sqlite://")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE props (id VARCHAR, sportsbook VARCHAR, line FLOAT)"))
            connection.execute(text("CREATE TABLE slip_items (id VARCHAR, prop_id VARCHAR)"))
            connection.execute(text("INSERT INTO props VALUES ('prop', 'Primary', 1.5)"))
            connection.execute(text("INSERT INTO slip_items VALUES ('pick', 'prop')"))
        with patch("scripts.migrate_slip_selections.engine", engine):
            migrate()
            with engine.begin() as connection:
                self.assertEqual(connection.execute(text("SELECT sportsbook, line FROM slip_items")).one(), ("Primary", 1.5))
                connection.execute(text("UPDATE props SET sportsbook = 'Changed', line = 2.5"))
            migrate()
            with engine.begin() as connection:
                self.assertEqual(connection.execute(text("SELECT sportsbook, line FROM slip_items")).one(), ("Primary", 1.5))
                connection.execute(text("UPDATE slip_items SET line = NULL"))
            migrate()
            with engine.begin() as connection:
                self.assertEqual(connection.execute(text("SELECT sportsbook, line FROM slip_items")).one(), ("Changed", 2.5))
        engine.dispose()
