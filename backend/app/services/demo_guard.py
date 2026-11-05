"""Fail-closed boundary for legacy synthetic-data tools.

Demo operations require a separately provisioned database named proppulse_demo
and an explicit process environment opt-in. Legacy unmarked props are uncertain,
not implicitly demo data. This module never creates or resets a database.
"""
import os

from app.models import Prop, PropBook, PropBookSnapshot, PlayerGameLog, FatigueScore


class DemoOperationRefused(RuntimeError):
    """Synthetic writes are unsafe for the selected environment or dataset."""


def require_demo_environment(bind):
    if os.environ.get("PROPPULSE_DEMO_MODE", "").lower() != "true":
        raise DemoOperationRefused(
            "Demo operation refused: explicitly set PROPPULSE_DEMO_MODE=true "
            "for an isolated proppulse_demo database."
        )
    url = getattr(bind, "url", None)
    if (url is None or url.get_backend_name() != "postgresql"
            or url.database != "proppulse_demo"):
        raise DemoOperationRefused(
            "Demo operation refused: the bound database must be the separate "
            "PostgreSQL database named proppulse_demo."
        )


def require_demo_dataset(db):
    """Check before *any* mutation, including calls to individual helpers.

All stored offers, snapshots, and provider history block synthetic writes, even
if their parent props appear to have demo labels. A missing/partial schema also
fails closed. No provider timestamp or real event ID may be relabeled as demo.
"""
    require_demo_environment(db.get_bind())
    try:
        if db.new or db.dirty or db.deleted:
            raise DemoOperationRefused(
                "Demo operation refused: the session contains unverified pending writes."
            )
        with db.no_autoflush:
            for model in (PropBook, PropBookSnapshot, PlayerGameLog):
                if db.query(model).first() is not None:
                    raise DemoOperationRefused(
                        "Demo operation refused: offers, snapshots, or game history "
                        "exist; provider-backed research data must be preserved."
                    )
            props = db.query(Prop).all()
            for prop in props:
                if (not isinstance(prop.odds_event_id, str)
                        or not prop.odds_event_id.startswith("demo:")
                        or prop.odds_sport_key != "demo"
                        or prop.sportsbook != "Demo"
                        or prop.odds_last_seen_at is not None):
                    raise DemoOperationRefused(
                        "Demo operation refused: provider-backed or unmarked props "
                        "exist. Only explicitly marked synthetic demo rows are eligible."
                    )
            demo_players = {prop.player_id for prop in props}
            if any(score.player_id not in demo_players
                   for score in db.query(FatigueScore).all()):
                raise DemoOperationRefused(
                    "Demo operation refused: fatigue records have no verified demo props."
                )
    except DemoOperationRefused:
        raise
    except Exception:
        raise DemoOperationRefused(
            "Demo operation refused: dataset identity could not be verified "
            "(including missing or outdated schema)."
        ) from None
