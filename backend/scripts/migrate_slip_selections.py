"""Add nullable saved sportsbook/line columns; safe to run more than once."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from app.database import engine


def migrate():
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("slip_items")}
        if "sportsbook" not in columns:
            connection.execute(text("ALTER TABLE slip_items ADD COLUMN sportsbook VARCHAR"))
        if "line" not in columns:
            connection.execute(text("ALTER TABLE slip_items ADD COLUMN line FLOAT"))
        # Pin legacy picks to today's primary offer once, preserving complete selections.
        connection.execute(text("""
            UPDATE slip_items
            SET sportsbook = props.sportsbook, line = props.line
            FROM props
            WHERE slip_items.prop_id = props.id
              AND (slip_items.sportsbook IS NULL OR slip_items.line IS NULL)
        """))
    print("Slip selection migration complete.")


if __name__ == "__main__":
    migrate()
