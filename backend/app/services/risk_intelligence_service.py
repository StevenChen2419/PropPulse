"""Experimental workload screening from observed logs, never injury/win probabilities.

Only providers implemented by fetch_player_game_logs are trusted. Missing ingestion
is reported explicitly instead of repurposing the NBA model or synthetic history.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math

from sqlalchemy.orm import joinedload

from app.models import PlayerGameLog, Prop

SPORTS = ("NBA", "WNBA", "MLB", "NFL", "NHL")
SOURCES = {"NBA": "espn_nba", "WNBA": "espn_wnba", "MLB": "mlb_stats_api",
           "NFL": "espn_nfl", "NHL": "espn_nhl"}
PITCHING = {"strikeouts", "hits_allowed", "earned_runs"}
HITTING = {"hits", "runs", "rbis", "total_bases", "home_runs"}
WORKLOAD = {
    "NBA": ("Minutes in last 7 days", "minutes"),
    "WNBA": ("Minutes in last 7 days", "minutes"),
    "MLB": ("Hitting appearances in last 7 days", "games"),
    "NFL": ("Snaps in last 7 days", "snaps"),
    "NHL": ("Ice time in last 7 days", "minutes"),
}


def _utc(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _assessment(player, event, prop_types, logs, now):
    sport = player.sport
    label, unit = WORKLOAD[sport]
    pitcher = sport == "MLB" and bool(PITCHING & prop_types)
    if pitcher:
        label, unit = "Pitches in last 7 days", "pitches"
    row = {"player": {"id": str(player.id), "name": player.name, "team_abbr": player.team_abbr, "sport": sport},
           "score": None, "label": "Unknown", "method": "unavailable", "reasons": [], "missing_data": [],
           "games_in_7d": None, "workload": {"label": label, "value": None, "unit": unit},
           "next_game": _utc(event).isoformat() + "Z"}
    if sport not in SOURCES:
        row["missing_data"].append(f"Verified {sport} game-log ingestion is not connected.")
        row["missing_data"].append({"NBA": "Basketball minutes are unavailable.",
                                    "NFL": "Snap counts and verified short-rest history are unavailable.",
                                    "NHL": "Time on ice and verified rest history are unavailable."}[sport])
        return row
    if not logs:
        row["missing_data"].append("No verified appearances in the last 7 days; rest and workload are unknown.")
        return row
    if sport == "MLB":
        # A two-way player's batting-only rows must not masquerade as pitching
        # appearances (or vice versa). Unidentifiable rows remain a data gap.
        relevant, ambiguous = [], False
        for log in logs:
            values = log.stats if isinstance(log.stats, dict) else {}
            pitching_row = any(k in values for k in PITCHING | {"pitches", "games_started"})
            hitting_row = any(k in values for k in HITTING | {"plate_appearances"})
            if (pitcher and pitching_row) or (not pitcher and hitting_row):
                relevant.append(log)
            elif not pitching_row and not hitting_row:
                ambiguous = True
        if ambiguous or not relevant:
            row["missing_data"].append("Recent appearances cannot be fully identified for this baseball role.")
            return row
        logs = relevant
    row["games_in_7d"] = len(logs)
    row["reasons"].append(f"{len(logs)} verified appearances observed in the last 7 days; history may be incomplete.")
    # Provider MLB logs carry a date rather than a precise game start time.
    rest_days = (_utc(event).date() - max(_utc(log.game_date).date() for log in logs)).days
    row["reasons"].append(f"Next game is {rest_days} calendar days after the latest observed appearance.")
    stats = [log.stats if isinstance(log.stats, dict) else {} for log in logs]
    if sport in {"NBA", "WNBA", "NFL", "NHL"} or pitcher:
        key = "pitches" if pitcher else {"NBA": "minutes", "WNBA": "minutes", "NFL": "offensive_snaps", "NHL": "time_on_ice"}[sport]
        activity = False
        if sport == "NFL" and any(not _number(s.get(key)) for s in stats):
            position = (getattr(player, "position", None) or "").upper()
            if position == "QB":
                key = "pass_attempts"
                row["workload"].update(label="Pass attempts in last 7 days", unit="attempts")
            elif position in {"RB", "WR", "TE"}:
                if all(_number(s.get("rush_attempts")) and _number(s.get("receptions")) for s in stats):
                    stats = [{**s, "touches": s["rush_attempts"] + s["receptions"]} for s in stats]
                    key = "touches"
                    row["workload"].update(label="Touches in last 7 days", unit="touches")
                elif all(_number(s.get("receptions")) for s in stats):
                    key = "receptions"
                    row["workload"].update(label="Receptions in last 7 days", unit="receptions")
                    row["missing_data"].append("Rushing activity is incomplete; receptions exclude unobserved rushing work.")
                else:
                    row["missing_data"].append("Complete rushing and receiving activity counts are unavailable.")
                    return row
            else:
                row["missing_data"].append("Snap counts are unavailable and the player role has no supported activity proxy.")
                return row
            activity = True
            row["missing_data"].append("Snap counts are unavailable; recorded offensive activity is an incomplete workload proxy.")
        if any(not _number(s.get(key)) for s in stats):
            row["missing_data"].append(f"Complete {key} counts are not stored for the recent verified appearances.")
            return row
        value = sum(s[key] for s in stats)
        # Ordinal screening thresholds, explicitly not fitted injury probabilities.
        moderate, high = (90, 180) if pitcher else {"NBA": (100, 150), "WNBA": (80, 120), "NFL": (60, 90), "NHL": (60, 90)}[sport]
        if activity:
            moderate, high = (30, 45) if key == "pass_attempts" else (6, 10) if key == "receptions" else (15, 25)
        score = 75 if value >= high else 45 if value >= moderate else 20
        if rest_days <= (3 if pitcher else 4 if sport == "NFL" else 1):
            score = min(100, score + 15)
            row["reasons"].append("Short calendar rest increases this experimental workload index.")
        row["method"] = "experimental_pitch_workload" if pitcher else {"NBA": "experimental_basketball_workload", "WNBA": "experimental_basketball_workload", "NFL": "experimental_snap_workload", "NHL": "experimental_ice_time_workload"}[sport]
        if activity:
            row["method"] = "experimental_offensive_activity"
    elif sport == "MLB" and HITTING & prop_types:
        if any(not any(_number(s.get(k)) for k in HITTING) for s in stats):
            row["missing_data"].append("Recent logs do not consistently identify hitting appearances.")
            return row
        value = len(stats)
        score = 75 if value >= 6 else 45 if value >= 4 else 20
        row["method"] = "experimental_hitter_activity"
        row["missing_data"].append("Travel and recovery are unavailable; appearance count is only an activity proxy.")
        if not all(_number(s.get("plate_appearances")) for s in stats):
            row["missing_data"].append("Plate-appearance counts are incomplete in the observed history.")
    else:
        row["missing_data"].append("Player role cannot be established from the active markets.")
        return row
    row.update(score=score / 100, label="High workload" if score >= 70 else "Moderate workload" if score >= 40 else "Lower observed workload")
    row["workload"]["value"] = round(value, 1)
    row["reasons"].append("Experimental ordinal workload index (0–100), not a probability or medical assessment.")
    return row


def build_risk_intelligence(db, sport=None):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    horizon = now + timedelta(days=7)
    start = now - timedelta(days=7)
    props = (db.query(Prop).options(joinedload(Prop.player)).filter(
        Prop.is_active.is_(True), Prop.game_time > now, Prop.game_time <= horizon,
        Prop.odds_event_id.isnot(None), ~Prop.odds_event_id.ilike("mock%"),
        ~Prop.odds_event_id.ilike("synthetic%"),
    ).order_by(Prop.game_time, Prop.id).limit(5000).all())
    players = {}
    for prop in props:
        event = (prop.odds_event_id or "").strip()
        if (not prop.is_active or not prop.game_time or not now < _utc(prop.game_time) <= horizon
                or not event or event.lower().startswith(("mock", "synthetic"))
                or prop.player.sport not in SPORTS):
            continue
        key = str(prop.player_id)
        if key not in players:
            players[key] = {"player": prop.player, "event": prop.game_time, "types": set()}
        if _utc(prop.game_time) < _utc(players[key]["event"]):
            players[key]["event"] = prop.game_time
        players[key]["types"].add(prop.prop_type)
    grouped = defaultdict(dict)
    if players:
        logs = (db.query(PlayerGameLog).filter(
            PlayerGameLog.player_id.in_(list(players)), PlayerGameLog.game_date >= start,
            PlayerGameLog.game_date < now, PlayerGameLog.source.in_(list(SOURCES.values())),
        ).order_by(PlayerGameLog.game_date.desc(), PlayerGameLog.id).limit(50000).all())
        for log in logs:
            key = str(log.player_id)
            if key not in players or not log.game_date:
                continue
            player = players[key]["player"]
            identity = str(log.external_game_id or "").strip()
            if (log.sport != player.sport or log.source != SOURCES.get(player.sport)
                    or not identity or identity.lower().startswith(("mock", "synthetic"))
                    or not start <= _utc(log.game_date) < now):
                continue
            if player.sport == "MLB" and _utc(log.game_date).date() == now.date():
                continue  # Date-only MLB rows cannot establish that today's game finished.
            grouped[key].setdefault(identity, log)
    rows = [_assessment(p["player"], p["event"], p["types"], list(grouped[k].values()), now)
            for k, p in players.items()]
    coverage = []
    for code in SPORTS:
        selected = [r for r in rows if r["player"]["sport"] == code]
        assessed = sum(r["score"] is not None for r in selected)
        coverage.append({"sport": code, "active_players": len(selected), "assessed_players": assessed,
                         "status": "no_upcoming_players" if not selected else "available" if assessed == len(selected) else "partial" if assessed else "missing_data",
                         "description": "Upcoming 7-day market coverage (up to 5,000 props); experimental workload screening from verified logs. Missing history is never treated as low risk."})
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["player"]["name"]))
    return {"sports": coverage, "players": [r for r in rows if sport is None or r["player"]["sport"] == sport],
            "generated_at": now.isoformat() + "Z"}
