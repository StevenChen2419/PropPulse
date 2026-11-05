"""Simulate movement only for explicitly marked, isolated synthetic demo props.

Requires PROPPULSE_DEMO_MODE=true and a separately provisioned PostgreSQL
database named proppulse_demo. Never requests provider data. Never writes the
live odds ingestion status file. Provider-backed or uncertain datasets refuse
the entire operation before changing any lines.
"""
import os
import random
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from app.database import SessionLocal, engine
from app.models import Prop
from app.services.demo_guard import (
    DemoOperationRefused, require_demo_dataset, require_demo_environment,
)

LINE_SHIFTS = [-1.5, -1.0, -0.5, -0.5, -0.5, 0.0, 0.0, 0.0, 0.0,
               0.5, 0.5, 0.5, 1.0, 1.5]


def apply_line_shifts(db, games=None) -> dict:
    """Direct helper calls enforce the same demo boundary as the CLI."""
    require_demo_dataset(db)
    if games:
        raise DemoOperationRefused(
            "Demo movement refused: real provider matchup context is unsupported."
        )
    props = db.query(Prop).filter(Prop.is_active == True).all()
    moved_up = moved_down = unchanged = 0
    for prop in props:
        old_line = prop.line
        new_line = max(0.5, round((old_line + random.choice(LINE_SHIFTS)) * 2) / 2)
        prop.line_24h_ago = old_line
        prop.line = new_line
        if new_line > old_line:
            moved_up += 1
        elif new_line < old_line:
            moved_down += 1
        else:
            unchanged += 1
    db.commit()
    return {"total": len(props), "moved_up": moved_up,
            "moved_down": moved_down, "unchanged": unchanged,
            "matchups": [], "live_games": 0}


def main() -> None:
    require_demo_environment(engine)
    db = SessionLocal()
    try:
        result = apply_line_shifts(db)
        print(f"Synthetic demo movement: {result['total']} props; "
              f"{result['moved_up']} up, {result['moved_down']} down, "
              f"{result['unchanged']} unchanged. No provider data requested.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
