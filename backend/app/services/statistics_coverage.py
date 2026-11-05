"""Coverage labels over existing season summaries, independent of price eligibility."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.services.game_log_fields import provider_season


def coverage_from_summary(summary, sport, *, now=None):
    now = now or datetime.now(timezone.utc)
    year = provider_season(sport, now.astimezone(ZoneInfo('America/New_York')))
    current = f'{year-1}-{str(year)[-2:]}' if sport in {'NBA','NHL'} else str(year)
    unavailable = summary is None
    summary = summary or {}
    season = summary.get('season', current)
    season_scope = 'historical' if season < current else 'current' if season == current else 'future'
    count = summary.get('recorded_appearances', 0)
    l5, l10 = summary.get('l5', {}), summary.get('l10', {})
    partial = l10.get('appearances', 0) < 10 or any(
        isinstance(value, dict) and value.get('valid_samples', 0) < l10.get('appearances', 0)
        for value in l10.values())
    state = ('source_unavailable' if unavailable else 'no_recorded_games' if not count else 'source_unavailable' if season_scope == 'future'
             else 'historical_season' if season_scope == 'historical'
             else 'partial_current_season' if partial and season_scope == 'current' else 'current_season')
    limitations = ['Source completeness is unknown; a recent game does not prove complete coverage.']
    if not summary.get('last_observed_at'):
        limitations.append('Source observation time unavailable; ingestion time is not substituted.')
    return dict(state=state, completeness='unknown', season_scope=season_scope,
        season=season, competition=summary.get('competition', 'Regular Season'), source=summary.get('source'),
        last_game_date=summary.get('latest_appearance'), source_observed_at=summary.get('last_observed_at'),
        recorded_appearances=count, l5_samples=l5.get('appearances', 0), l10_samples=l10.get('appearances', 0),
        recorded_weeks=summary.get('recorded_weeks', []), limitations=limitations)


def player_statistics_coverage(player, logs, *, now=None):
    from app.services.sports_statistics import build_sport_summary
    if player.sport not in {'NBA','WNBA','NHL','NFL','MLB'}:
        return None
    summary = build_sport_summary(player, logs, now=now)
    return summary['coverage']
