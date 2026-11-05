"""Exact sportsbook-line analysis over existing verified season appearances."""
from decimal import Decimal
from datetime import datetime, timezone

from app.services.game_log_fields import number
from app.services.sports_statistics import eligible_logs, build_sport_summary, utc, EASTERN, SIGNED

BASKETBALL = {key: (key,) for key in ('points', 'rebounds', 'assists', 'threes')}
BASKETBALL['pra'] = ('points', 'rebounds', 'assists')
MARKET_METRICS = {
    'NBA': BASKETBALL, 'WNBA': BASKETBALL,
    'NHL': {key: (key,) for key in ('shots_on_goal', 'goals', 'assists', 'points', 'saves')},
    'NFL': {**{key: (key,) for key in ('pass_yds', 'rush_yds', 'reception_yds', 'receptions',
                                     'pass_tds', 'rush_tds', 'receiving_tds')},
            'rush_reception_yds': ('rush_yds', 'reception_yds')},
    'MLB': {key: (key,) for key in ('hits', 'total_bases', 'runs', 'rbis', 'home_runs', 'strikeouts', 'outs_recorded')},
}


def exact_window(games, side):
    over = sum(g['outcome'] == 'over' for g in games)
    under = sum(g['outcome'] == 'under' for g in games)
    pushes = sum(g['outcome'] == 'push' for g in games)
    valid = over + under + pushes
    hits, losses = (over, under) if side == 'over' else (under, over)
    return dict(appearances=len(games), valid_samples=valid, missing_samples=len(games)-valid,
        over_hits=over, under_hits=under, pushes=pushes, hits=hits, losses=losses,
        raw_hit_rate=hits/valid if valid else None, settled_decisions=over+under,
        settled_hit_rate=hits/(over+under) if over+under else None)


def build_exact_line_research(player, logs, *, market, line, side='over', season=None,
                             competition='Regular Season', reference=None, now=None,
                             summary=None, opponent_id=None):
    now = utc(now or datetime.now(timezone.utc))
    if number(line, signed=True) is None or side not in {'over', 'under'}:
        raise ValueError('Finite line and Over/Under side required')
    reference = min(utc(reference or now), now)
    summary = summary or build_sport_summary(player, logs, season=season, competition=competition,
                                            reference=reference, now=now)
    season = summary['season']
    metrics = MARKET_METRICS.get(player.sport, {}).get(market)
    result = dict(player_id=str(player.id), sport=player.sport, market=market, metrics=list(metrics or []),
        line=line, side=side, season=season, competition=competition,
        source='nba_com_stats' if player.sport == 'NBA' else summary.get('source'),
        coverage=summary.get('coverage'), reference_at=reference.isoformat(), last_game_date=None,
        source_observed_at=None, games=[], opponents=[], current_opponent_id=opponent_id,
        limitations=['Recorded coverage may be incomplete. Descriptive hit rates are not future probabilities.',
            'L5/L10 select appearances before excluding missing metrics; pushes are never wins.',
            'Raw hit rate uses all valid outcomes; settled rate explicitly excludes pushes.'])
    if metrics is None:
        return dict(result, status='unsupported_market', l5=exact_window([], side),
                    l10=exact_window([], side), season_window=exact_window([], side))
    if player.sport == 'NBA':
        from app.services.nba_season_summary import recorded_nba_scope
        scope = recorded_nba_scope(player, logs, season=season, competition=competition, reference=reference, now=now)
        # ESPN's unseparated legacy competition history remains separately labeled.
        verified = {id(stats) for _, stats in scope['eligible']} if scope['source'] == 'nba_com_stats' else set()
        rows = [row for row in scope['nba_scope'] if id(row.stats) in verified]
    else:
        rows = eligible_logs(player, logs, season=season, competition=competition, reference=reference, now=now)
    rows.sort(key=lambda row: (utc(row.game_date), row.external_game_id), reverse=True)
    games = []
    for row in rows:
        stats = row.stats
        meta = stats.get('_nba' if player.sport == 'NBA' else '_research', {})
        role = meta.get('role', 'player')
        role_ok = (player.sport != 'NHL' or role == ('goalie' if market == 'saves' else 'skater'))
        role_ok &= (player.sport != 'MLB' or role in
                    ({'pitcher', 'two_way'} if market in {'strikeouts', 'outs_recorded'} else {'batter', 'two_way'}))
        # Role-incompatible appearances must not fill a market's recent windows.
        if not role_ok:
            continue
        values = [number(stats.get(key), signed=key in SIGNED) for key in metrics]
        value = sum((Decimal(str(v)) for v in values), Decimal(0)) if all(v is not None for v in values) else None
        boundary = Decimal(str(line))
        outcome = 'missing' if value is None else 'over' if value > boundary else 'under' if value < boundary else 'push'
        games.append(dict(game_id=row.external_game_id, game_date=utc(row.game_date).astimezone(EASTERN).date().isoformat(),
            value=float(value) if value is not None else None, outcome=outcome,
            opponent_id=meta.get('opponent_id') if isinstance(meta.get('opponent_id'), str) and meta['opponent_id'].strip() else None,
            source=row.source, source_observed_at=meta.get('observed_at')))
    for identity in sorted({g['opponent_id'] for g in games if g['opponent_id']}):
        sample = [g for g in games if g['opponent_id'] == identity]
        result['opponents'].append(dict(opponent_id=identity, source=summary.get('source'), games=sample[:10],
            l5=exact_window(sample[:5], side), l10=exact_window(sample[:10], side), season_window=exact_window(sample, side)))
    if games:
        result['last_game_date'] = games[0]['game_date']
        result['source_observed_at'] = max((g['source_observed_at'] for g in games if g['source_observed_at']),
            key=lambda value: utc(datetime.fromisoformat(value)), default=None)
    result.update(games=games[:10], l5=exact_window(games[:5], side), l10=exact_window(games[:10], side),
                  season_window=exact_window(games, side),
                  status='available' if any(g['value'] is not None for g in games) else 'missing_metric' if games
                      else 'unsupported_role' if rows else 'no_recorded_games')
    from app.services.statistics_coverage import coverage_from_summary
    result['coverage'] = coverage_from_summary(dict(season=season,competition=competition,source=result['source'],
        latest_appearance=result['last_game_date'],last_observed_at=result['source_observed_at'],
        recorded_appearances=len(games),l5=dict(appearances=result['l5']['appearances']),
        l10=dict(appearances=result['l10']['appearances'],metric=dict(valid_samples=result['l10']['valid_samples']))),
        player.sport,now=now)
    return result


def resolve_research_offer(prop, db, *, sportsbook=None, line=None, side='over'):
    """Resolve a stored offer or retained snapshot, never arbitrary client prices."""
    from fastapi import HTTPException
    from app.models import PropBookSnapshot
    from app.services.offer_service import offer_availability
    if (sportsbook is None) != (line is None):
        raise HTTPException(400, 'Supply sportsbook and offer_line together')
    book, boundary = (sportsbook, line) if sportsbook is not None else (prop.sportsbook, prop.line)
    if not book or len(book) > 80 or number(boundary, signed=True) is None:
        raise HTTPException(422, 'Invalid sportsbook or line')
    offer = next((o for o in prop.book_offers if o.sportsbook == book and o.line == boundary), None)
    primary = book == prop.sportsbook and boundary == prop.line
    if not offer and not primary and not db.query(PropBookSnapshot.id).filter(
            PropBookSnapshot.prop_id == prop.id, PropBookSnapshot.sportsbook == book,
            PropBookSnapshot.line == boundary).first():
        raise HTTPException(400, 'Requested sportsbook line has no stored evidence for this Prop')
    status = offer_availability(prop, book, boundary, side)
    if offer is None:
        status = dict(availability='market_unavailable', actionable=False, odds=None,
            source='unavailable', provider_observed_at=None, refreshed_at=None, expires_at=None)
    return dict(sportsbook=book, line=boundary, side=side, **status)
