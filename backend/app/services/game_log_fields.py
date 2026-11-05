"""Normalize provider workload fields without turning missing values into zero."""
import math


def number(value, duration=False, signed=False):
    if isinstance(value, bool) or value is None:
        return None
    try:
        if duration and ":" in str(value):
            minutes, seconds = str(value).split(":")
            if not 0 <= float(seconds) < 60:
                return None
            result = float(minutes) + float(seconds) / 60
        else:
            result = float(value)
        return result if math.isfinite(result) and (signed or result >= 0) else None
    except (ValueError, TypeError):
        return None


def espn_stats(sport, names, values):
    raw = dict(zip(names, values))
    basketball = {"minutes": "minutes", "points": "points", "rebounds": "totalRebounds",
                  "assists": "assists", "blocks": "blocks", "steals": "steals"}
    fields = basketball if sport in {"NBA", "WNBA"} else {
        "NFL": {"pass_attempts": "passingAttempts", "pass_yds": "passingYards",
                "pass_tds": "passingTouchdowns", "rush_attempts": "rushingAttempts",
                "rush_yds": "rushingYards", "receptions": "receptions",
                "reception_yds": "receivingYards", "offensive_snaps": "offensiveSnaps"},
        "NHL": {"time_on_ice": "timeOnIcePerGame", "goals": "goals", "assists": "assists",
                "points": "points", "shots_on_goal": "shotsTotal"},
    }.get(sport, {})
    stats = {}
    for key, provider_key in fields.items():
        value = number(raw.get(provider_key), duration=key in {"minutes", "time_on_ice"},
                       signed=key in {"pass_yds", "rush_yds", "reception_yds"})
        if value is not None:
            stats[key] = value
    if sport in {"NBA", "WNBA"}:
        made = raw.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted")
        threes = number(str(made).split("-", 1)[0]) if made is not None else None
        if threes is not None:
            stats["threes"] = threes
        if all(key in stats for key in ("points", "rebounds", "assists")):
            stats["pra"] = sum(stats[key] for key in ("points", "rebounds", "assists"))
    return stats


def provider_season(sport, today):
    """ESPN uses the ending year for basketball/hockey and starting year for NFL."""
    if sport in {"NBA", "NHL"}:
        return today.year + (today.month >= 10)
    if sport == "NFL" and today.month <= 2:
        return today.year - 1
    return today.year
