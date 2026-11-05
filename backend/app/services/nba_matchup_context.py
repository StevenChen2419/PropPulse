"""Small, read-only NBA matchup context over already stored results/statistics.

No Event-to-NBA-game crosswalk or schedule-completeness claim is made here.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
import re

from sqlalchemy import select

from app.models import NBAEvidenceRecord
from app.services.game_log_fields import number
from app.services.nba_season_summary import EASTERN, METRICS, _observation, _utc, recorded_nba_scope

# Reviewed exact Odds Event full-name -> canonical NBA ID associations. No fuzzy
# matching, abbreviations, current Player.team, or Prop opponent strings.
EVENT_TEAMS = {
    "Atlanta Hawks": "1610612737", "Boston Celtics": "1610612738",
    "Cleveland Cavaliers": "1610612739", "New Orleans Pelicans": "1610612740",
    "Chicago Bulls": "1610612741", "Dallas Mavericks": "1610612742",
    "Denver Nuggets": "1610612743", "Golden State Warriors": "1610612744",
    "Houston Rockets": "1610612745", "Los Angeles Clippers": "1610612746",
    "Los Angeles Lakers": "1610612747", "Miami Heat": "1610612748",
    "Milwaukee Bucks": "1610612749", "Minnesota Timberwolves": "1610612750",
    "Brooklyn Nets": "1610612751", "New York Knicks": "1610612752",
    "Orlando Magic": "1610612753", "Indiana Pacers": "1610612754",
    "Philadelphia 76ers": "1610612755", "Phoenix Suns": "1610612756",
    "Portland Trail Blazers": "1610612757", "Sacramento Kings": "1610612758",
    "San Antonio Spurs": "1610612759", "Oklahoma City Thunder": "1610612760",
    "Toronto Raptors": "1610612761", "Utah Jazz": "1610612762",
    "Memphis Grizzlies": "1610612763", "Washington Wizards": "1610612764",
    "Detroit Pistons": "1610612765", "Charlotte Hornets": "1610612766",
}
TEAM_NAMES = {identity: name for name, identity in EVENT_TEAMS.items()}
TEAM_CONTEXT_DAYS = 14


def _window(sample):
    result = {"appearances": len(sample),
              "coverage_start": sample[-1][0].isoformat() if sample else None,
              "coverage_end": sample[0][0].isoformat() if sample else None}
    for metric in METRICS:
        values = [value for _, stats in sample
                  if (value := number(stats.get(metric))) is not None
                  and (metric != "minutes" or value <= 100)]
        result[metric] = {"average": round(mean(values), 2) if values else None,
                          "valid_samples": len(values)}
    return result


def _valid_identity(day, stats):
    meta = stats.get("_nba", {})
    return (meta.get("provider") == "nba_api.stats.playergamelog"
            and meta.get("team_id") in TEAM_NAMES and meta.get("opponent_id") in TEAM_NAMES
            and meta["team_id"] != meta["opponent_id"]
            and meta.get("game_date") == day.isoformat()
            and isinstance(meta.get("nba_game_id"), str)
            and re.fullmatch(r"00[24][0-9]{7}", meta["nba_game_id"]) is not None)


def _recorded_team_game(db, team_id, reference, now):
    """Accept only paired-final LeagueGameLog normalization; conflicts fail closed."""
    cutoff = min(reference, now)
    reference_day = reference.astimezone(EASTERN).date()
    games = defaultdict(list)
    rows = db.scalars(select(NBAEvidenceRecord).where(
        NBAEvidenceRecord.provider == "nba_com", NBAEvidenceRecord.sport == "NBA",
        NBAEvidenceRecord.kind == "game",
        NBAEvidenceRecord.source == "nba_api.stats.leaguegamelog",
        NBAEvidenceRecord.observed_at <= cutoff.replace(tzinfo=None))).all()
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        # Retain every as-known observation for conflict detection, including a
        # changed team/date/status, rather than silently choosing a favorable one.
        games[row.game_id].append((row, payload))
    supported = []
    for game_id, versions in games.items():
        if not any(team_id in (p.get("home_team_id"), p.get("away_team_id")) for _, p in versions):
            continue
        if any(p != versions[0][1] for _, p in versions):
            return None, "Conflicting recorded team game observations; team rest is unavailable."
        row, payload = max(versions, key=lambda item: _utc(item[0].observed_at))
        at = _observation(payload.get("game_at"))
        observed = _utc(row.observed_at)
        if (not isinstance(game_id, str) or re.fullmatch(r"[0-9]{10}", game_id) is None
                or row.identity != game_id or payload.get("status") != "completed"
                or payload.get("time_precision") != "eastern_date" or at is None
                or payload.get("home_team_id") not in TEAM_NAMES
                or payload.get("away_team_id") not in TEAM_NAMES
                or payload["home_team_id"] == payload["away_team_id"]):
            continue
        day = at.astimezone(EASTERN).date()
        if day >= reference_day or day >= observed.astimezone(EASTERN).date() or observed > cutoff:
            continue
        supported.append((day, game_id, row))
    # Multiple canonical games for this team/day contradict usable date evidence.
    if any(sum(other[0] == day for other in supported) > 1 for day, _, _ in supported):
        return None, "Conflicting recorded team games on the same Eastern date; team rest is unavailable."
    if not supported:
        return None, "No supported recorded completed team game before this reference."
    day, game_id, row = max(supported, key=lambda item: item[0])
    return dict(game_id=game_id, date=day.isoformat(), source=row.source,
                observed_at=_utc(row.observed_at).isoformat(), date_precision="eastern_date"), None


def build_stored_matchup_context(db, player, logs, *, prop=None, season=None,
                                 competition="Regular Season", now=None):
    if player.sport != "NBA":
        return None
    unavailable = lambda reason: dict(status="unavailable", reason=reason,
                                      team_context=None, opponent_history=None)
    event = getattr(prop, "event", None) if prop is not None else None
    if (event is None or str(getattr(prop, "player_id", "")) != str(player.id)
            or str(getattr(prop, "event_id", "")) != str(event.id)
            or getattr(event, "sport_key", None) != "basketball_nba"):
        return unavailable("Select an exact NBA prop with a linked Event for matchup context.")
    reference = _utc(getattr(event, "scheduled_start_at", None))
    if reference is None:
        return unavailable("The selected Event has no supported start time.")
    home, away = EVENT_TEAMS.get(event.home_team), EVENT_TEAMS.get(event.away_team)
    if not home or not away or home == away:
        return unavailable("Selected Event participants do not have an exact supported NBA mapping.")
    now = _utc(now or datetime.now(timezone.utc))
    scope = recorded_nba_scope(player, logs, reference=reference, now=now,
                               season=season, competition=competition)
    eligible = scope["eligible"] if scope["source"] == "nba_com_stats" else []
    supported = [(day, stats) for day, stats in eligible if _valid_identity(day, stats)]
    day = reference.astimezone(EASTERN).date()
    # Team identity belongs to the selected Event, independently of the season /
    # competition requested for descriptive statistics. Reuse each stored NBA
    # scope's existing as-known appearance guards; union affiliations so changing
    # the statistics scope cannot conceal a recent trade or conflicting team.
    identity_scopes = set()
    for log in logs:
        stats = log.stats if isinstance(log.stats, dict) else {}
        meta = stats.get("_nba", {})
        if (str(getattr(log, "player_id", "")) == str(player.id) and log.sport == "NBA"
                and log.source == "nba_com_stats" and isinstance(meta, dict)
                and isinstance(meta.get("season"), str)
                and meta.get("competition") in ("Regular Season", "Playoffs")):
            identity_scopes.add((meta["season"], meta["competition"]))
    recent = []
    for identity_season, identity_competition in sorted(identity_scopes):
        if (identity_season, identity_competition) == (scope["season"], competition):
            identity_scope = scope
        else:
            identity_scope = recorded_nba_scope(player, logs, reference=reference, now=now,
                season=identity_season, competition=identity_competition)
        recent.extend((at, stats) for at, stats in identity_scope["eligible"]
                      if identity_scope["source"] == "nba_com_stats"
                      and _valid_identity(at, stats) and 0 < (day-at).days <= TEAM_CONTEXT_DAYS)
    if not recent:
        return unavailable("Recent reviewed NBA player-team context is missing or older than 14 days; player research remains available.")
    identities = {stats["_nba"]["team_id"] for _, stats in recent}
    if len(identities) != 1:
        return unavailable("Recent recorded player teams conflict or include a trade; selected team context is withheld.")
    team = identities.pop()
    latest_observed = max(_observation(stats["_nba"]["observed_at"]) for _, stats in recent)
    if reference-latest_observed > timedelta(days=TEAM_CONTEXT_DAYS) or team not in (home, away):
        return unavailable("Recorded player-team context is stale or does not match the selected Event participants.")
    opponent = away if team == home else home
    sample = [(at, stats) for at, stats in supported if stats["_nba"]["opponent_id"] == opponent]
    overall, l5, l10 = _window(sample), _window(sample[:5]), _window(sample[:10])
    history = dict(status="available" if sample else "unavailable", opponent_id=opponent,
        opponent_name=TEAM_NAMES[opponent], season=scope["season"], competition=competition,
        source="nba_com_stats", recorded_appearances=len(sample),
        coverage_start=overall["coverage_start"], coverage_end=overall["coverage_end"],
        overall=overall, l5=l5, l10=l10,
        notes=["Partial recorded coverage; each statistic uses its own valid-value count within the newest opponent appearances.",
               "Historical opponent performance is descriptive, not a prediction or current defensive-strength measure."])
    last, reason = _recorded_team_game(db, team, reference, now)
    gap = (day-datetime.fromisoformat(last["date"]).date()).days if last else None
    team_context = dict(team_id=team, team_name=TEAM_NAMES[team], opponent_id=opponent,
        opponent_name=TEAM_NAMES[opponent], event_id=str(event.id), prop_id=str(prop.id),
        reference_date=day.isoformat(), last_recorded_game=last, calendar_day_gap=gap,
        full_intervening_days=max(gap-1, 0) if gap is not None else None,
        conditional_back_to_back="yes" if gap == 1 else "unknown",
        notes=["Latest recorded completed team game only; schedule coverage is incomplete and missing games do not prove rest.",
               "Team calendar gaps are separate from player rest. Back-to-back Yes is conditional on the team playing the selected Event.",
               "Team identity is supported by recent reviewed recorded appearances, not a current roster certification."] + ([reason] if reason else []))
    return dict(status="available", reason=None, team_context=team_context, opponent_history=history)
