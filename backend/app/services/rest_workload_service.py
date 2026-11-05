"""Read-only NBA research from retained provider appearances; never a risk model.

The event store is odds inventory, not a complete team schedule. A gap between
appearances is therefore an observed-history gap, not verified team rest.
"""
from collections import Counter
from dataclasses import dataclass
import json
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from zoneinfo import ZoneInfo
from typing import Literal

from app.services.game_log_fields import number, provider_season

EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class GameEvidence:
    """Internal normalized evidence, not an asserted upstream ESPN contract."""
    game_id: str
    home_team_id: str
    away_team_id: str
    game_at: datetime
    status: Literal["completed", "postponed", "cancelled", "unfinished", "unknown"]
    source: str
    observed_at: datetime
    completed_at: datetime | None = None
    provider: Literal["espn", "nba_com"] = "espn"
    sport: Literal["NBA"] = "NBA"
    time_precision: Literal["instant", "eastern_date"] = "instant"


@dataclass(frozen=True)
class ParticipationEvidence:
    player_id: str
    game_id: str
    team_id: str
    state: Literal["appeared", "dnp", "inactive", "unknown"]
    source: str
    observed_at: datetime
    provider: Literal["espn", "nba_com"] = "espn"
    sport: Literal["NBA"] = "NBA"


@dataclass(frozen=True)
class MembershipEvidence:
    player_id: str
    team_id: str
    starts_at: datetime
    ends_at: datetime | None
    source: str
    observed_at: datetime
    provider: Literal["espn", "nba_com"] = "espn"
    sport: Literal["NBA"] = "NBA"


@dataclass(frozen=True)
class ScheduleCoverageEvidence:
    team_id: str
    starts_at: datetime
    ends_at: datetime
    complete: bool
    source: str
    observed_at: datetime
    provider: Literal["espn", "nba_com"] = "espn"
    sport: Literal["NBA"] = "NBA"


@dataclass(frozen=True)
class VerifiedRestEvidence:
    """Only a future audited retrieval adapter may supply live evidence.

    A coverage assertion means *all* games/statuses for the stable team ID in
    [starts_at, ends_at) were successfully reconciled, not just HTTP success.
    Membership intervals are [starts_at, ends_at); None means no recorded end.
    Existing game-log rows, Event inventory and mutable player.team do not
    establish any of these evidence types. Public APIs accept no such assertions.
    """
    games: tuple[GameEvidence, ...] = ()
    participation: tuple[ParticipationEvidence, ...] = ()
    membership: tuple[MembershipEvidence, ...] = ()
    coverage: tuple[ScheduleCoverageEvidence, ...] = ()


def _utc(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def build_verified_rest(player_id, *, reference, now, evidence=None):
    """Separate final/participation facts from incomplete recorded-log heuristics.

    Exact missed counts require continuous membership and schedule coverage plus
    explicit participation for every completed game since the recorded appearance.
    Missing rows never mean DNP; known DNP/inactive remain a separate lower bound.
    """
    evidence = evidence or VerifiedRestEvidence()
    now, reference = _utc(now), _utc(reference)
    invalid, conflicts = 0, 0
    sources = set()

    def trusted(item):
        observed = _utc(item.observed_at)
        return bool(item.provider in {"espn", "nba_com"} and item.sport == "NBA"
                    and isinstance(item.source, str) and item.source.strip()
                    and not (item.provider == "nba_com" and item.source.startswith("nba_api.live."))
                    and observed and observed <= now)

    groups = {}
    for item in evidence.games:
        at, completed = _utc(item.game_at), _utc(item.completed_at)
        if (not trusted(item) or not item.game_id or not item.home_team_id or not item.away_team_id
                or item.home_team_id == item.away_team_id or at is None
                or item.time_precision not in {"instant", "eastern_date"}
                or item.time_precision == "eastern_date" and (at.astimezone(EASTERN).time().isoformat() != "00:00:00"
                    or completed is not None or at.astimezone(EASTERN).date() >= _utc(item.observed_at).astimezone(EASTERN).date())
                or item.status not in {"completed", "postponed", "cancelled", "unfinished", "unknown"}
                or item.status == "completed" and (at >= now or at >= reference
                    or _utc(item.observed_at) < at or completed is not None and
                    (completed < at or completed > _utc(item.observed_at) or completed >= reference)
                    or completed is None and _utc(item.observed_at) > reference)):
            invalid += 1
            continue
        signature = (item.provider, item.home_team_id, item.away_team_id, at, item.status, completed, item.time_precision)
        groups.setdefault(item.game_id, {}).setdefault(signature, []).append(item)
    games = {}
    for game_id, variants in groups.items():
        if len(variants) != 1:
            observations = [item for items in variants.values() for item in items]
            # Stats and Live use the same NBA game identity. A date-only anchor
            # and a precise start on that Eastern date are compatible evidence,
            # provided teams, status and completion observations agree. Never
            # use this to join ESPN IDs or reconcile contradictory game states.
            precise = [item for item in observations if item.time_precision == "instant"]
            dates = [item for item in observations if item.time_precision == "eastern_date"]
            consistent = len({(item.provider, item.home_team_id, item.away_team_id, item.status,
                              _utc(item.game_at).astimezone(EASTERN).date(), _utc(item.completed_at))
                              for item in observations}) == 1
            if (precise and dates and consistent and all(item.provider == "nba_com" for item in observations)
                    and len({_utc(item.game_at) for item in precise}) == 1
                    and all(_utc(item.game_at).astimezone(EASTERN).time().isoformat() == "00:00:00" for item in dates)):
                item = precise[0]
                sources.update(observation.source for observation in observations)
            else:
                conflicts += sum(len(items) for items in variants.values())
                continue
        else:
            item = next(iter(variants.values()))[0]
        if item.status == "completed":
            games[game_id] = item
            sources.add(item.source)
    # No audited crosswalk exists for conflicting provider IDs. NBA teams do
    # not play doubleheaders; same Eastern-day identities are quarantined even
    # if conflicting start times differ slightly.
    team_instants = {}
    for game_id, item in games.items():
        for team in (item.home_team_id, item.away_team_id):
            team_instants.setdefault((team, _utc(item.game_at).astimezone(EASTERN).date()), set()).add(game_id)
    duplicate_ids = set().union(*(ids for ids in team_instants.values() if len(ids) > 1))
    conflicts += len(duplicate_ids)
    games = {game_id: item for game_id, item in games.items() if game_id not in duplicate_ids}

    memberships = []
    for item in evidence.membership:
        start, end = _utc(item.starts_at), _utc(item.ends_at)
        if (str(item.player_id) != str(player_id) or not trusted(item) or not item.team_id
                or start is None or start > now or item.ends_at is not None and (end is None or end <= start)):
            invalid += 1
            continue
        memberships.append(item)
        sources.add(item.source)

    def member_teams(at):
        return {item.team_id for item in memberships
                if _utc(item.starts_at) <= at and (item.ends_at is None or at < _utc(item.ends_at))}

    # Conflicting overlapping membership is unresolved, including game-specific
    # team claims; never fall back to the player's mutable current team string.
    membership_conflict = any(left.team_id != right.team_id
        and max(_utc(left.starts_at), _utc(right.starts_at))
        < min(_utc(left.ends_at) or reference, _utc(right.ends_at) or reference)
        for index, left in enumerate(memberships) for right in memberships[index + 1:])
    if membership_conflict:
        conflicts += 1

    participation_groups = {}
    for item in evidence.participation:
        game = games.get(item.game_id)
        if (str(item.player_id) != str(player_id) or not trusted(item) or game is None
                or item.provider != game.provider
                or item.team_id not in {game.home_team_id, game.away_team_id}
                or item.state not in {"appeared", "dnp", "inactive", "unknown"}
                or _utc(item.observed_at) < _utc(game.game_at)
                or item.state in {"dnp", "inactive"} and _utc(item.observed_at)
                   < (_utc(game.completed_at) or _utc(game.observed_at))):
            invalid += 1
            continue
        known_teams = member_teams(_utc(game.game_at))
        if len(known_teams) > 1 or known_teams and item.team_id not in known_teams:
            conflicts += 1
            continue
        participation_groups.setdefault(item.game_id, {}).setdefault((item.team_id, item.state), []).append(item)
    participation = {}
    for game_id, variants in participation_groups.items():
        if len(variants) != 1:
            conflicts += sum(len(items) for items in variants.values())
            continue
        participation[game_id] = next(iter(variants.values()))[0]
        sources.add(participation[game_id].source)

    # No cross-provider game crosswalk is established. Two providers describing
    # the same player's Eastern date may be duplicate or contradictory claims;
    # neither may inflate missed totals or silently override the other.
    player_dates = {}
    for game_id, item in participation.items():
        day = _utc(games[game_id].game_at).astimezone(EASTERN).date()
        player_dates.setdefault(day, []).append(game_id)
    overlapping = {game_id for ids in player_dates.values()
                   if len({participation[identity].provider for identity in ids}) > 1
                   for game_id in ids}
    conflicts += len(overlapping)
    participation = {identity: item for identity, item in participation.items() if identity not in overlapping}

    coverages = []
    for item in evidence.coverage:
        start, end = _utc(item.starts_at), _utc(item.ends_at)
        if (not trusted(item) or not item.team_id or start is None or end is None or start >= end
                or item.complete is not True or end > now or _utc(item.observed_at) < end):
            invalid += 1
            continue
        coverages.append(item)
        sources.add(item.source)

    def covered(team_id, start, end):
        if start >= end:
            return True
        cursor = start
        for item in sorted((item for item in coverages if item.team_id == team_id), key=lambda item: _utc(item.starts_at)):
            if _utc(item.starts_at) > cursor:
                break
            if _utc(item.ends_at) > cursor:
                cursor = _utc(item.ends_at)
            if cursor >= end:
                return True
        return False

    def membership_and_schedule_complete(start, end):
        if end > now or start is None or start >= end or membership_conflict or conflicts or invalid:
            return False
        boundaries = sorted({start, end, *(_utc(item.starts_at) for item in memberships
                                         if start < _utc(item.starts_at) < end),
                             *(_utc(item.ends_at) for item in memberships if item.ends_at is not None
                               and start < _utc(item.ends_at) < end)})
        for left, right in zip(boundaries, boundaries[1:]):
            teams = member_teams(left)
            if len(teams) != 1 or not covered(next(iter(teams)), left, right):
                return False
        return True

    appeared = [games[game_id] for game_id, item in participation.items() if item.state == "appeared"]
    last_appearance = max(appeared, key=lambda item: _utc(item.game_at), default=None)
    start = _utc(last_appearance.game_at) if last_appearance is not None else None
    reference_teams = member_teams(reference)
    team_id = next(iter(reference_teams)) if len(reference_teams) == 1 else None
    team_games = [item for item in games.values() if team_id in {item.home_team_id, item.away_team_id}] if team_id else []
    last_team_game = max(team_games, key=lambda item: _utc(item.game_at), default=None)
    relevant = []
    for game in games.values():
        at = _utc(game.game_at)
        if start is not None and at <= start:
            continue
        membership = member_teams(at)
        item = participation.get(game.game_id)
        # A game-specific explicit team assignment can supply partial evidence
        # even if its dated membership interval was not retrieved.
        if (len(membership) == 1 and next(iter(membership)) in {game.home_team_id, game.away_team_id}
                or item is not None):
            relevant.append(game)
    dnp = sum(participation[game.game_id].state == "dnp" for game in relevant if game.game_id in participation)
    inactive = sum(participation[game.game_id].state == "inactive" for game in relevant if game.game_id in participation)
    unknown = sum(participation[game.game_id].state == "unknown" for game in relevant if game.game_id in participation)
    uncovered = sum(game.game_id not in participation for game in relevant)
    schedule_complete = membership_and_schedule_complete(start, reference)
    exact = schedule_complete and not unknown and not uncovered and not conflicts
    team_complete = (last_team_game is not None and reference <= now and not conflicts and not invalid
                     and covered(team_id, _utc(last_team_game.game_at), reference))

    def game_result(game, side, complete, appearance=False):
        if game is None:
            return None
        gap = (reference.astimezone(EASTERN).date() - _utc(game.game_at).astimezone(EASTERN).date()).days
        item = participation.get(game.game_id) if appearance else None
        return {"game_id": game.game_id, "team_id": side, "game_at": _utc(game.game_at).isoformat(),
                "provider": game.provider, "sport": game.sport, "source": game.source,
                "time_precision": game.time_precision,
                "observed_at": _utc(game.observed_at).isoformat(),
                "participation_source": item.source if item else None,
                "participation_observed_at": _utc(item.observed_at).isoformat() if item else None,
                "completed_at": _utc(game.completed_at).isoformat() if game.completed_at is not None else None,
                "gap_days": gap, "full_rest_days": max(gap - 1, 0),
                "status": "confirmed" if complete else "partial"}

    appearance_result = game_result(last_appearance, participation[last_appearance.game_id].team_id if last_appearance else None, exact, True)
    team_result = game_result(last_team_game, team_id, team_complete)
    # Positive evidence of a team game on the previous calendar day proves B2B.
    # A negative claim requires complete coverage; a candidate on the same day
    # cannot rule out an additional prior-day game without that coverage.
    previous_day_game = any((reference.astimezone(EASTERN).date() - _utc(game.game_at).astimezone(EASTERN).date()).days == 1
                            for game in team_games)
    b2b = True if previous_day_game and not conflicts else False if team_complete else None
    status = "confirmed" if exact and team_complete else "partial" if appearance_result or team_result or relevant else "unknown"
    notes = ["Confirmed refers to explicit final status and participation evidence, never age, points, minutes or a missing log.",
             "Latest confirmed recorded games may not be the most recent actual games when coverage is partial.",
             "Gaps use Eastern calendar game dates; full rest days = max(gap minus 1, 0), not measured recovery hours.",
             "Exact missed games require continuous dated membership and complete team schedules through the reference, plus known participation for each completed game.",
             "DNP and inactive counts are explicit observations since the latest confirmed recorded appearance; absent participation is uncovered, never a missed game."]
    if evidence == VerifiedRestEvidence():
        notes.append("Verified schedule and participation retrieval is not connected; current retained logs cannot establish these facts.")
    if any(game.time_precision == "eastern_date" for game in games.values()):
        notes.append("NBA Stats game_at values anchor an Eastern calendar date at midnight; they are not actual start or completion times.")
    if reference > now:
        notes.append("Upcoming reference extends beyond evaluation; future schedule completeness is unknown.")
    if conflicts:
        notes.append("Conflicting evidence was excluded; exact recency, negative back-to-back and missed totals are withheld.")
    if invalid:
        notes.append("Invalid or unsupported evidence was excluded; exact totals and negative back-to-back claims are withheld.")
    if start is None:
        notes.append("No confirmed appearance baseline; since-appearance counts are withheld. Zero evidence counts do not establish zero missed games.")
        dnp, inactive, unknown, uncovered = 0, 0, 0, 0
    return {"status": status, "reference_at": reference.isoformat(), "context_team_id": team_id,
            "provenance": sorted(sources), "last_confirmed_appearance": appearance_result,
            "last_completed_team_game": team_result, "team_back_to_back": b2b,
            "confirmed_missed_games": dnp + inactive if exact else None,
            "partial_missed_games_lower_bound": dnp + inactive if start is not None else None,
            "dnp_games": dnp, "inactive_games": inactive,
            "unknown_participation_games": unknown, "uncovered_games": uncovered,
            "schedule_complete": schedule_complete, "notes": notes,
            "evidence_counts": {"games": len(games), "participation": len(participation),
                                "membership": len(memberships), "coverage": len(coverages),
                                "excluded_conflicts": conflicts, "excluded_invalid": invalid}}


def _category(days):
    return "back_to_back" if days == 1 else "short_rest" if days == 2 else "extended_rest" if days >= 3 else None


def _dates(rows):
    dates = [row["date"].isoformat() for row in rows]
    return {"date_start": min(dates) if dates else None, "date_end": max(dates) if dates else None}


def _window(rows, expected):
    minutes = [row["minutes"] for row in rows if row["minutes"] is not None]
    return {"games": len(minutes), "observed_games": len(rows),
            "average_minutes": round(mean(minutes), 2) if minutes else None,
            **_dates(rows), "seasons": sorted({row["season"] for row in rows}),
            "insufficient_sample": len(minutes) < expected}


def _base_exclusion(player, log, now, reference):
    stats = log.stats if isinstance(log.stats, dict) else {}
    date = _utc(log.game_date)
    identity = getattr(log, "external_game_id", None)
    competition = str(getattr(log, "season_type", None) or stats.get("season_type") or "").lower()
    if player.sport != "NBA":
        return "unsupported_sport"
    if getattr(log, "sport", None) != "NBA":
        return "sport_mismatch"
    if str(getattr(log, "player_id", player.id)) != str(player.id):
        return "player_mismatch"
    if getattr(log, "source", None) != "espn_nba":
        return "unsupported_source"
    if any(token in str(identity).lower() for token in ("synthetic", "demo", "mock")):
        return "synthetic_identity"
    if not date:
        return "invalid_date"
    if date >= now:
        return "future_game"
    if date >= reference:
        return "at_or_after_reference"
    if stats.get("completed") is False:
        return "not_completed"
    if date.date() == now.date() and stats.get("completed") is not True:
        return "completion_unknown_today"
    if "preseason" in competition.replace("-", "").replace(" ", ""):
        return "preseason"
    if not identity:
        return "missing_game_identity"
    if number(stats.get("minutes"), duration=True) == 0:
        return "did_not_play"
    minutes = number(stats.get("minutes"), duration=True)
    if not (minutes is not None and 0 < minutes <= 100) and not any(
            number(stats.get(key)) is not None for key in ("points", "rebounds", "assists", "blocks", "steals", "threes")):
        return "no_observed_statistics"
    return None


def build_rest_workload(player, logs, *, prop=None, event=None, now=None, verified_evidence=None):
    """Deterministic calculations with explicit context and exclusion accounting."""
    now = _utc(now or datetime.now(timezone.utc))
    event = event if event is not None else getattr(prop, "event", None)
    invalid_event = event is not None and getattr(event, "sport_key", "basketball_nba") != "basketball_nba"
    if invalid_event:
        event = None
    reference = _utc(getattr(event, "scheduled_start_at", None)) or now
    reference_day = reference.astimezone(EASTERN).date()
    season = provider_season(player.sport, reference)
    excluded, rows, seen_ids, seen_days = Counter(), [], set(), set()
    profiles = {}
    for log in logs:
        date = _utc(log.game_date)
        if _base_exclusion(player, log, now, reference) is None:
            profile = json.dumps([date.isoformat(), log.stats, getattr(log, "opponent", None),
                                  getattr(log, "is_home", None)], sort_keys=True, default=str)
            for key in (("id", getattr(log, "external_game_id", None)),
                        ("day", date.astimezone(EASTERN).date())):
                profiles.setdefault(key, set()).add(profile)
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    ordered = sorted(logs, key=lambda row: (_utc(row.game_date) or minimum,
                     str(getattr(row, "external_game_id", "")), str(getattr(row, "id", ""))), reverse=True)
    for log in ordered:
        stats = log.stats if isinstance(log.stats, dict) else {}
        date = _utc(log.game_date)
        identity = getattr(log, "external_game_id", None)
        reason = _base_exclusion(player, log, now, reference)
        if reason is None and (len(profiles.get(("id", identity), set())) > 1 or len(profiles.get(("day", date.astimezone(EASTERN).date()), set())) > 1):
            reason = "conflicting_game_logs"
        elif reason is None and (identity in seen_ids or date.astimezone(EASTERN).date() in seen_days):
            reason = "duplicate_game"
        if reason:
            excluded[reason] += 1
            continue
        seen_ids.add(identity)
        seen_days.add(date.astimezone(EASTERN).date())
        minutes = number(stats.get("minutes"), duration=True)
        # Above 100 minutes is treated as malformed, never clipped or imputed.
        minutes = minutes if minutes is not None and minutes <= 100 else None
        rows.append({"date": date, "day": date.astimezone(EASTERN).date(),
                     "season": provider_season("NBA", date), "minutes": minutes,
                     "points": number(stats.get("points")), "source": log.source})
    l5, l10 = _window(rows[:5], 5), _window(rows[:10], 10)
    current = [row for row in rows if row["season"] == season]
    baseline = _window(current, 5)
    prior = _window(rows[5:10], 5)
    delta = (round(l5["average_minutes"] - baseline["average_minutes"], 2)
             if l5["average_minutes"] is not None and baseline["average_minutes"] is not None else None)
    trend = (round(l5["average_minutes"] - prior["average_minutes"], 2)
             if l5["games"] == 5 and prior["games"] == 5 else None)
    minutes = [row["minutes"] for row in rows[:10] if row["minutes"] is not None]
    days = (reference_day - rows[0]["day"]).days if rows else None
    count = lambda size: sum(reference - timedelta(days=size) <= row["date"] < reference for row in rows)
    splits = []
    for category in ("back_to_back", "short_rest", "extended_rest"):
        # Adjacent appearances within one season; first appearance and offseason
        # transitions cannot establish a rest category.
        sample = [row for index, row in enumerate(rows[:-1])
                  if row["season"] == rows[index + 1]["season"]
                  and _category((row["day"] - rows[index + 1]["day"]).days) == category]
        minute_values = [row["minutes"] for row in sample if row["minutes"] is not None]
        points = [row["points"] for row in sample if row["points"] is not None]
        splits.append({"category": category, "games": len(sample), "minutes_games": len(minute_values),
                       "average_minutes": round(mean(minute_values), 2) if minute_values else None,
                       "points_games": len(points), "average_points": round(mean(points), 2) if points else None,
                       **_dates(sample)})
    notes = ["Retained player appearances are incomplete; counts are lower bounds, not a verified team schedule.",
             "Completion is inferred from prior UTC-date provider statistics unless explicitly marked completed.",
             "Rest uses Eastern calendar dates; rolling windows use UTC instants [reference minus N days, reference).",
             "L5/L10 span seasons and retain missing-minute games in the window; games counts only valid minute samples.",
             "Season uses ESPN ending year (October through September); regular season and playoffs are not separated.",
             "Historical rest splits describe gaps between retained appearances; missed games and travel are unknown."]
    if event is None:
        notes.append("No authoritative Event context; legacy Prop dates are not used to infer a verified schedule.")
    if invalid_event:
        notes.append("Linked Event sport conflicts with NBA player research; its schedule is excluded.")
    if reference > now:
        notes.append("Upcoming Event reference; intervening games after evaluation may be missing.")
    verified = build_verified_rest(player.id, reference=reference, now=now,
                                   evidence=verified_evidence if player.sport == "NBA" else None)
    if event is None:
        verified["team_back_to_back"] = None
        verified["notes"].append("Back-to-back status requires an authoritative selected Event; an as-of clock is not a scheduled game.")
    return {"status": "unsupported_sport" if player.sport != "NBA" else "available" if rows else "no_history",
            "player_id": str(player.id), "sport": player.sport, "classification": "observed_and_derived",
            "evaluated_at": now.isoformat(),
            "reference": {"at": reference.isoformat(), "source": "event" if event is not None else "as_of",
                          "event_id": str(event.id) if event is not None else None,
                          "prop_id": str(prop.id) if prop is not None else None},
            "coverage": {"stored_games": len(logs), "eligible_games": len(rows),
                         "excluded_counts": dict(sorted(excluded.items())), **_dates(rows),
                         "sources": sorted({row["source"] for row in rows}), "schedule_complete": False, "notes": notes},
            "rest": {"days_since_last_game": days, "back_to_back": days == 1 if days is not None else None,
                     "category": _category(days) if days is not None else None,
                     "games_in_7d": count(7) if rows else None, "games_in_14d": count(14) if rows else None,
                     "schedule_density": round(count(7) / 7, 3) if rows else None,
                     "classification": "derived",
                     "explanation": "Observed appearance gaps: 1 Eastern calendar day = back-to-back; 2 = short rest; 3+ = extended rest. Density = recorded games in 7 days / 7. Gaps do not verify team rest."},
            "workload": {"l5": l5, "l10": l10, "season": baseline, "l5_vs_season": delta,
                         "minutes_trend": trend, "variability": round(pstdev(minutes), 2) if len(minutes) >= 2 else None,
                         "missing_minutes": sum(row["minutes"] is None for row in rows),
                         "explanation": "Averages use valid minutes only (0 excluded as did-not-play; >100 invalid). L5 minus season is minutes/game; trend is last 5 minus preceding 5, requiring all 10 minute samples. Variability is population standard deviation of L10 minutes, requiring 2 samples. Season sample below 5 is flagged."},
            "rest_splits": splits,
            "verified": verified,
            "interpretation": {"classification": "heuristic", "label": "Descriptive workload context",
                               "explanation": "Rest categories are heuristics, not injury risk, performance predictions or betting edge. Existing fatigue models are experimental and are not used here. Possession-based usage is unavailable.",
                               "experimental_model_used": False}}
