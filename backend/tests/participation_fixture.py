"""Normalized synthetic participation records for disposable browser fixtures only.

This module makes no provider requests and never opens a database. The caller
persists the manifest through the production reconciliation adapter inside its
explicit disposable-database transaction.
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def participation_manifest(now, *, confirmed_player_id, partial_player_id):
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    eastern = ZoneInfo("America/New_York")
    # Fixture gaps are calendar days, including DST transitions, rather than
    # consecutive 24-hour UTC durations that can land on the same local date.
    reference = datetime.combine(now.astimezone(eastern).date() - timedelta(days=2), time(18), eastern)
    secondary_reference = reference + timedelta(days=1)
    observed = now - timedelta(minutes=5)
    start = reference - timedelta(days=6)
    records = []

    def iso(value):
        return value.isoformat() if value is not None else None

    def record(kind, identity, payload, **context):
        records.append({"kind": kind, "identity": identity, "source": "synthetic_fixture",
                        "observed_at": iso(observed), "payload": payload, **context})

    teams = ["fixture-confirmed-team", "fixture-partial-team"]
    for team in [*teams, "fixture-opponent"]:
        record("team", team, {"name": team})
    for player, athlete, team in [(confirmed_player_id, "980001", teams[0]),
                                   (partial_player_id, "980002", teams[1])]:
        record("athlete", athlete, {}, player_id=player)
        record("membership", f"membership-{athlete}",
               {"athlete_id": athlete, "starts_at": iso(start), "ends_at": None},
               player_id=player, team_id=team)

    def game(identity, days, team, player, athlete, state):
        at = reference - timedelta(days=days)
        record("game", identity, {"home_team_id": team, "away_team_id": "fixture-opponent",
               "scheduled_at": iso(at), "game_at": iso(at), "completed_at": iso(at + timedelta(hours=2)),
               "status": "completed"}, game_id=identity)
        if state is not None:
            record("participation", f"participation-{identity}-{athlete}",
                   {"athlete_id": athlete, "state": state}, game_id=identity, team_id=team, player_id=player)
            record("coverage", f"boxscore-{identity}", {"coverage_type": "boxscore", "complete": True,
                   "reconciled": True, "athlete_ids": [athlete]}, game_id=identity, team_id=team)

    for identity, days, state in [("990001", 3, "appeared"), ("990002", 2, "dnp"), ("990003", 1, "inactive")]:
        game(identity, days, teams[0], confirmed_player_id, "980001", state)
    record("coverage", "schedule-confirmed", {"coverage_type": "schedule", "starts_at": iso(start),
           "ends_at": iso(secondary_reference), "complete": True, "reconciled": True,
           "game_ids": ["990001", "990002", "990003"]}, team_id=teams[0])
    for identity, days, state in [("990101", 5, "appeared"), ("990102", 4, "dnp"),
                                  ("990103", 3, "unknown"), ("990104", 2, None)]:
        game(identity, days, teams[1], partial_player_id, "980002", state)
    return {"format": "proppulse-nba-evidence-fixture-v1", "fixture_only": True,
            "provider": "espn", "sport": "NBA", "date_start": start.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
            "date_end": secondary_reference.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
            "team_ids": teams, "records": records}, reference.astimezone(timezone.utc).replace(tzinfo=None), secondary_reference.astimezone(timezone.utc).replace(tzinfo=None)
