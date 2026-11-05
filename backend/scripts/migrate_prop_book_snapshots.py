"""Create the local sportsbook offer snapshot table and its indexes."""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from app.database import Base, SessionLocal, engine
from app.models import PropBook, PropBookSnapshot


def migrate() -> None:
    Base.metadata.create_all(bind=engine, tables=[PropBookSnapshot.__table__])
    db = SessionLocal()
    seeded = 0
    try:
        existing_pairs = {
            (prop_id, sportsbook)
            for prop_id, sportsbook in db.query(
                PropBookSnapshot.prop_id,
                PropBookSnapshot.sportsbook,
            ).distinct()
        }
        for offer in db.query(PropBook).all():
            key = (offer.prop_id, offer.sportsbook)
            if key in existing_pairs:
                continue
            db.add(PropBookSnapshot(
                prop_id=offer.prop_id,
                sportsbook=offer.sportsbook,
                line=offer.line,
                over_odds=offer.over_odds,
                under_odds=offer.under_odds,
                captured_at=offer.updated_at,
            ))
            existing_pairs.add(key)
            seeded += 1
        db.commit()
    finally:
        db.close()
    print(f"Prop book snapshot migration complete. Baselines seeded: {seeded}")


if __name__ == "__main__":
    migrate()
