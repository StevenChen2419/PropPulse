"""Exact-line historical observations, with independent recent/season windows."""
from collections import Counter
from datetime import datetime, timezone
from statistics import mean, median

from app.models import PlayerGameLog, Prop
from app.services.game_log_fields import number, provider_season

TREND_SPORTS = {"MLB", "WNBA", "NBA", "NFL", "NHL"}
VERIFIED_LOG_SOURCES = {"mlb_stats_api", "espn_mlb", "espn_wnba", "espn_nba", "espn_nfl", "espn_nhl", "wehoop_wnba_stats", "nhl_web", "nflverse"}
COMPETITION_SCOPE = "Provider history excluding preseason; regular season and playoffs are not separately identified."
COMPLETION_SCOPE = "Completion is inferred from provider statistics on prior UTC dates; same-day unconfirmed results are excluded."


def _utc(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _window(values: list[dict], size: int | None = None, season: int | None = None) -> dict:
    sample = values[:size] if size else values
    hits = sum(item["result"] == "hit" for item in sample)
    pushes = sum(item["result"] == "push" for item in sample)
    decisions = len(sample) - pushes
    seasons = sorted({item["season"] for item in sample if "season" in item})
    scope = ("empty" if not seasons else "current_season" if seasons == [season]
             else "mixed_seasons" if season in seasons else "previous_seasons")
    return {"games": len(sample), "decisions": decisions, "hits": hits,
            "pushes": pushes, "hit_rate": round(hits / decisions, 3) if decisions else None,
            "seasons": seasons, "season_scope": scope}


def _line_trends(results, line, season, current=None):
    if not results:
        return None
    current = current if current is not None else [item for item in results if item["season"] == season]
    values = [item["value"] for item in results]
    return {"line": line, "side": "over", "season": season,
            "l5": _window(results, 5, season), "l10": _window(results, 10, season),
            "season_window": _window(current, season=season),
            "average": round(mean(values), 2), "median": round(median(values), 2),
            "recent_games": results[:10],
            "recent_scope": "Most recent eligible historical observations across seasons.",
            "competition_scope": COMPETITION_SCOPE}


def build_history_research(sport: str, prop_type: str, line: float, season: int,
                           game_logs: list[PlayerGameLog], *, before_game=None, now=None) -> dict:
    """Classify each row once, without substituting missing statistics or seasons.

    Legacy rows lack final/competition metadata. Prior-date provider statistics
    are the completion proxy; unknown same-day rows fail closed. Explicit final
    and preseason metadata, when present, is respected without guessing it.
    """
    now = _utc(now or datetime.now(timezone.utc))
    before_game = _utc(before_game) or now
    excluded = Counter()
    results, seen = [], set()
    valid_market_games = 0
    for log in game_logs:
        stats = log.stats if isinstance(log.stats, dict) else {}
        if number(stats.get(prop_type), signed=prop_type in {"pass_yds", "rush_yds", "reception_yds"}) is not None:
            valid_market_games += 1
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    for log in sorted(game_logs, key=lambda item: _utc(item.game_date) or minimum, reverse=True):
        stats = log.stats if isinstance(log.stats, dict) else {}
        game_date = _utc(log.game_date)
        raw = stats.get(prop_type)
        value = number(raw, signed=prop_type in {"pass_yds", "rush_yds", "reception_yds"})
        source = getattr(log, "source", None)
        identity = getattr(log, "external_game_id", None)
        # Reviewed MLB records qualify the same official gamePk that the legacy
        # importer stores bare. Treat them as one game in exact-line history.
        if sport == "MLB" and source == "mlb_stats_api" and identity:
            identity = identity.removeprefix("mlb_stats_api:")
        competition = str(getattr(log, "season_type", None) or stats.get("season_type") or "").casefold()
        completed = stats.get("completed")
        meta = stats.get("_research")
        reviewed = False
        if isinstance(meta, dict):
            from types import SimpleNamespace
            from app.services.sports_statistics import eligible_logs
            reviewed = bool(eligible_logs(SimpleNamespace(id=log.player_id, sport=sport), [log],
                season=meta.get("season"), competition="Regular Season", now=now, reference=before_game))
        reason = None
        if sport not in TREND_SPORTS:
            reason = "unsupported_sport"
        elif getattr(log, "sport", sport) != sport:
            reason = "sport_mismatch"
        elif meta is not None and not reviewed:
            reason = "unverified_research_scope"
        elif not reviewed and source not in ({"mlb_stats_api", "espn_mlb"} if sport == "MLB" else {f"espn_{sport.lower()}"}):
            reason = "unsupported_source"
        elif game_date is None:
            reason = "invalid_date"
        elif game_date >= before_game:
            reason = "at_or_after_prop"
        elif game_date >= now:
            reason = "future_game"
        elif "preseason" in competition.replace("-", "").replace(" ", ""):
            reason = "preseason"
        elif completed is False:
            reason = "not_completed"
        elif game_date.date() == now.date() and completed is not True:
            reason = "completion_unknown_today"
        elif raw is None:
            reason = "missing_statistic"
        elif value is None:
            reason = "invalid_statistic"
        elif identity and identity in seen:
            reason = "duplicate_game"
        if reason:
            excluded[reason] += 1
            continue
        if identity:
            seen.add(identity)
        recorded_season = provider_season(sport, game_date)
        if reviewed:
            recorded_season = int(meta['season'][:4]) + (1 if sport == 'NHL' else 0)
        results.append({"game_date": game_date.date().isoformat(), "opponent": log.opponent,
                        "is_home": getattr(log, "is_home", None), "value": value,
                        "result": "hit" if value > line else "push" if value == line else "miss",
                        "season": recorded_season})
    current = [item for item in results if item["season"] == season]
    status = ("available" if results else "no_history" if not game_logs
              else "no_valid_market_statistics" if not valid_market_games else "excluded_history")
    history = {"status": status, "stored_games": len(game_logs), "valid_market_games": valid_market_games,
               "eligible_games": len(results), "current_season_games": len(current),
               "previous_season_games": sum(item["season"] < season for item in results),
               "selected_season": season, "excluded_counts": dict(sorted(excluded.items())),
               "insufficient_l5": len(results) < 5, "insufficient_l10": len(results) < 10,
               "competition_scope": COMPETITION_SCOPE, "completion_scope": COMPLETION_SCOPE}
    trends = _line_trends(results, line, season, current)
    return {"results": results, "trends": trends, "history": history}


def build_exact_line_trends(prop: Prop, game_logs: list[PlayerGameLog], *, history_cache=None) -> dict | None:
    from app.services.game_identity_service import game_start
    start = game_start(prop)
    season = provider_season(prop.player.sport, start or datetime.now(timezone.utc))
    if history_cache is not None:
        day = datetime.now(timezone.utc).date()
        # Only past-date observations have clock-independent eligibility during
        # this UTC day. Today's/future/invalid dates keep the original path.
        if all((date := _utc(log.game_date)) is not None and date.date() < day for log in game_logs):
            key = (prop.player_id, prop.player.sport, prop.prop_type, start, season, day)
            if key not in history_cache:
                original = build_history_research(prop.player.sport, prop.prop_type, prop.line, season,
                                                  game_logs, before_game=start)
                history_cache[key] = original["results"]
                return original["trends"]
            # Source/competition/date/statistic validation, duplicate exclusion
            # and ordering are line-independent. Reclassify every eligible
            # value at this exact line, using the same window implementation.
            results = [{**item, "result": "hit" if item["value"] > prop.line else
                        "push" if item["value"] == prop.line else "miss"}
                       for item in history_cache[key]]
            return _line_trends(results, prop.line, season)
    return build_line_trends(prop.player.sport, prop.prop_type, prop.line, season,
                             game_logs, before_game=start)


def build_line_results(sport: str, prop_type: str, line: float, season: int,
                       game_logs: list[PlayerGameLog], *, before_game=None) -> list[dict]:
    """Compatibility helper for callers explicitly requesting one season."""
    return [item for item in build_history_research(sport, prop_type, line, season,
             game_logs, before_game=before_game)["results"] if item["season"] == season]


def build_line_trends(sport: str, prop_type: str, line: float, season: int,
                      game_logs: list[PlayerGameLog], *, before_game=None) -> dict | None:
    return build_history_research(sport, prop_type, line, season, game_logs,
                                  before_game=before_game)["trends"]


def build_line_split(results: list[dict], season: int | None = None) -> dict:
    return _window(results, season=season)
