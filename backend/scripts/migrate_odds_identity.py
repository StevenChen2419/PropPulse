"""Add nullable Odds API identity columns to an existing local props table."""

import os
import sys

from sqlalchemy import text

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from app.database import engine


MIGRATION_STATEMENTS = (
    "ALTER TABLE props ADD COLUMN IF NOT EXISTS odds_event_id VARCHAR",
    "ALTER TABLE props ADD COLUMN IF NOT EXISTS odds_sport_key VARCHAR",
    "ALTER TABLE props ADD COLUMN IF NOT EXISTS odds_last_seen_at TIMESTAMP WITHOUT TIME ZONE",
    "CREATE INDEX IF NOT EXISTS ix_props_odds_event_id ON props (odds_event_id)",
    "CREATE INDEX IF NOT EXISTS ix_props_odds_sport_key ON props (odds_sport_key)",
    "CREATE INDEX IF NOT EXISTS ix_props_odds_last_seen_at ON props (odds_last_seen_at)",
)


def migrate() -> None:
    with engine.begin() as connection:
        for statement in MIGRATION_STATEMENTS:
            connection.execute(text(statement))
    print("Odds identity migration complete.")


if __name__ == "__main__":
    migrate()
