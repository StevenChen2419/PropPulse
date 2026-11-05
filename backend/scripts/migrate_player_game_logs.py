"""Create the sport-neutral historical player game-log table."""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from app.database import Base, engine
from app import models  # noqa: F401 - registers all model tables


def migrate() -> None:
    Base.metadata.create_all(bind=engine)
    print("Player game-log migration complete.")


if __name__ == "__main__":
    migrate()
