"""Compact recorded-season statistics; deliberately independent of ranking/history."""
from datetime import datetime, timezone
from statistics import mean
from zoneinfo import ZoneInfo

from app.services.game_log_fields import number, provider_season
from app.services.rest_workload_service import _base_exclusion

EASTERN = ZoneInfo("America/New_York")
METRICS = ("points", "rebounds", "assists", "threes", "minutes")


def _utc(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _observation(value):
    try:
        result = datetime.fromisoformat(value)
        return _utc(result) if result.tzinfo else None
    except (TypeError, ValueError):
        return None


def recorded_nba_scope(player, logs, *, reference=None, now=None,
                             season=None, competition="Regular Season"):
    now = _utc(now or datetime.now(timezone.utc))
    reference = _utc(reference) or now
    reference_date = reference.astimezone(EASTERN).date()
    # Statistics default to the current season even when a retained Prop points
    # to an old Event. The Event remains the rest/as-known reference only.
    end_year = provider_season("NBA", now.astimezone(EASTERN))
    current_season = f"{end_year - 1}-{str(end_year)[-2:]}"
    season = season or f"{end_year - 1}-{str(end_year)[-2:]}"
    nba_scope = []
    for log in logs:
        stats = log.stats if isinstance(log.stats, dict) else {}
        meta = stats.get("_nba", {})
        if (str(getattr(log, "player_id", player.id)) == str(player.id) and log.sport == "NBA"
                and log.source == "nba_com_stats" and isinstance(meta, dict)
                and meta.get("season") == season and meta.get("competition") == competition
                and meta.get("reviewed_crosswalk") and meta.get("date_precision") == "eastern_date"):
            nba_scope.append(log)
    # Legacy ESPN observations do not distinguish Regular Season from playoffs.
    # Keep that disclosed historical fallback, but never call it current form.
    source = "nba_com_stats" if nba_scope or season >= current_season else "espn_nba"
    eligible, seen, observed = [], set(), []
    for log in sorted(logs, key=lambda row: _utc(row.game_date) or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        if str(getattr(log, "player_id", player.id)) != str(player.id) or log.sport != "NBA" or log.source != source:
            continue
        stats = log.stats if isinstance(log.stats, dict) else {}
        at = _utc(log.game_date)
        if at is None:
            continue
        day = at.astimezone(EASTERN).date()
        if day >= min(reference_date, now.astimezone(EASTERN).date()):
            continue
        if source == "nba_com_stats":
            if log not in nba_scope or stats["_nba"].get("appearance") is not True:
                continue
            observation = _observation(stats["_nba"].get("observed_at"))
            if observation is None or observation > min(reference, now):
                continue
            observed.append(observation)
        else:
            if _base_exclusion(player, log, now, reference) is not None:
                continue
            log_end = provider_season("NBA", at.astimezone(EASTERN))
            if f"{log_end - 1}-{str(log_end)[-2:]}" != season:
                continue
        if log.external_game_id in seen:
            continue
        seen.add(log.external_game_id)
        eligible.append((day, stats))

    return dict(source=source, nba_scope=nba_scope, eligible=eligible, observed=observed,
                season=season, reference=reference, now=now, reference_date=reference_date)


def build_nba_season_summary(player, logs, *, reference=None, now=None,
                             season=None, competition="Regular Season"):
    if player.sport != "NBA":
        return None
    scope = recorded_nba_scope(player, logs, reference=reference, now=now,
                               season=season, competition=competition)
    source, nba_scope = scope["source"], scope["nba_scope"]
    eligible, observed = scope["eligible"], scope["observed"]
    season, reference, now = scope["season"], scope["reference"], scope["now"]
    reference_date = scope["reference_date"]

    def window(size):
        sample = eligible[:size]
        result = {"appearances": len(sample)}
        for metric in METRICS:
            values = [value for _, stats in sample
                      if (value := number(stats.get(metric))) is not None
                      and (metric != "minutes" or value <= 100)]
            result[metric] = {"average": round(mean(values), 2) if values else None,
                              "valid_samples": len(values)}
        return result

    latest = eligible[0][0] if eligible else None
    gap = (reference_date - latest).days if latest else None
    notes = ["Recorded coverage is partial; this does not establish complete season history or missed games."]
    if source == "espn_nba":
        notes.append("ESPN fallback: regular season and playoffs are not separately identified; last provider observation is unavailable.")
    if not eligible:
        notes.append("No eligible recorded appearances in this season and reference scope.")
        if source == "nba_com_stats":
            notes.append("No NBA.com appearances available in this scope; historical ESPN results are not substituted. Player statistics are independent of odds and team-context availability.")
    if reference > now:
        notes.append("Rest is measured at the selected upcoming game; intervening appearances may be missing.")
    l5, l10 = window(5), window(10)
    if len(eligible) < 10 or any(l10[key]["valid_samples"] < l10["appearances"] for key in METRICS):
        notes.append("Small or incomplete samples: each metric uses only its valid values within the selected appearances.")
    result = {"status": "available" if eligible else "unavailable", "season": season,
            "competition": competition if source == "nba_com_stats" else "Provider history (competition not separated)",
            "source": source if eligible or nba_scope else None,
            "coverage_start": eligible[-1][0].isoformat() if eligible else None,
            "coverage_end": latest.isoformat() if latest else None,
            "last_observed_at": max(observed).isoformat() if observed else None,
            "recorded_appearances": len(eligible), "latest_appearance": latest.isoformat() if latest else None,
            "date_precision": "eastern_date" if latest else None,
            "reference_date": reference_date.isoformat(), "calendar_day_gap": gap,
            "full_intervening_days": max(gap - 1, 0) if gap is not None else None,
            "metrics": [dict(key=key, label=label) for key,label in
                [('points','Points'),('rebounds','Rebounds'),('assists','Assists'),('threes','3PM'),('minutes','Minutes')]],
            "l5": l5, "l10": l10, "notes": notes}
    from app.services.statistics_coverage import coverage_from_summary
    result['coverage'] = coverage_from_summary(result, 'NBA', now=now)
    return result
