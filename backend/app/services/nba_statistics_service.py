"""Explicit offline NBA statistics import; no fetching, scheduling or evidence writes.

The caller owns the outer transaction/commit. A savepoint makes every batch atomic
without committing unrelated pending application work. No records are deleted.
"""
from sqlalchemy import select

from app.models import Player, PlayerGameLog
from app.services.nba_api_provider import normalize_player_statistics


def import_player_statistics(db, payload, *, observed_at, crosswalk, season,
                             competition, max_records=1000):
    records = normalize_player_statistics(payload, observed_at=observed_at,
        crosswalk=crosswalk, season=season, competition=competition, max_records=max_records)
    counts = dict(inserted=0, updated=0, unchanged=0, records=len(records))
    # begin_nested flushes pending work before opening its savepoint. Require a
    # clean session so an import cannot inadvertently flush unrelated changes.
    if db.new or db.dirty or db.deleted:
        raise ValueError("Statistics import requires a clean session")
    with db.begin_nested():
        players = set(row["player_id"] for row in records)
        accepted = {p.id for p in db.scalars(select(Player).where(Player.id.in_(players), Player.sport == "NBA"))}
        if accepted != players:
            raise ValueError("Reviewed crosswalk requires exact existing NBA Player UUIDs")
        for record in records:
            existing = db.scalar(select(PlayerGameLog).where(
                PlayerGameLog.player_id == record["player_id"],
                PlayerGameLog.external_game_id == record["external_game_id"]).with_for_update())
            if existing is None:
                db.add(PlayerGameLog(**record))
                counts["inserted"] += 1
            else:
                old = existing.stats.get("_nba", {}) if isinstance(existing.stats, dict) else {}
                new = record["stats"]["_nba"]
                if (existing.source != "nba_com_stats" or existing.sport != "NBA"
                        or any(old.get(key) != new[key] for key in
                               ("nba_player_id", "nba_game_id", "season", "competition"))):
                    raise ValueError("Existing game identity/source conflicts with NBA import")
                if old.get("observed_at", "") > new["observed_at"]:
                    raise ValueError("Older NBA observation cannot overwrite accepted statistics")
                if all(getattr(existing, key) == value for key, value in record.items()):
                    counts["unchanged"] += 1
                else:
                    for key, value in record.items():
                        setattr(existing, key, value)
                    counts["updated"] += 1
        db.flush()
    return counts
