"""Invented contract examples only; never provider artifacts or live coverage.

Field references: wehoop column_descriptions.yaml; NHL game-log reference;
nflreadr load_player_stats week schema + schedules; MLB StatsAPI gameLog splits.
"""
from copy import deepcopy

PLAYER = '11111111-1111-4111-8111-111111111111'
SOURCES = {'WNBA': 'wehoop_wnba_stats', 'NHL': 'nhl_web', 'NFL': 'nflverse', 'MLB': 'mlb_stats_api'}


def fixture(sport, role=None):
    source = SOURCES[sport]
    season = '2025-26' if sport == 'NHL' else '2025'
    athlete = '00-0000001' if sport == 'NFL' else '12345'
    role = role or ('skater' if sport == 'NHL' else 'batter' if sport == 'MLB' else 'player')
    response = dict(athlete_id=athlete, role=role)
    if sport == 'WNBA':
        response['payload'] = [dict(player_id=12345, season_id='22025', game_id='1022500001', game_date='2025-06-10',
            wl='W', team_id=1, pts=0, reb=4, ast=3, fg3m=None, min='24:30')]
        response['schedule'] = [dict(game_id='1022500001', home_team_id=1, away_team_id=2)]
    elif sport == 'NHL':
        response['request_path']='/v1/player/12345/game-log/20252026/2'
        response['payload'] = dict(playerId=12345, seasonId=20252026, gameTypeId=2, gameLog=[dict(
            gameId=2025020001, gameDate='2025-10-10', opponentAbbrev='AAA', teamAbbrev='BBB', homeRoadFlag='H',
            goals=1, assists=2, points=3, shots=5, toi='21:30', saves=26)])
    elif sport == 'NFL':
        response['summary_level'] = 'week'
        response['payload'] = [dict(player_id=athlete, season=2025, season_type='REG', week=1, team='AAA',
            opponent_team='BBB', passing_yards=220, passing_tds=2, rushing_yards=-2, rushing_tds=0,
            receiving_yards=None, receptions=0, receiving_tds=0)]
        response['schedule'] = [dict(game_id='2025_01_AAA_BBB', season=2025, week=1, game_type='REG',
            away_team='AAA', home_team='BBB', gameday='2025-09-07', home_score=20, away_score=10)]
    else:
        response['request_path']='/api/v1/people/12345/stats'
        response['request_params']=dict(stats='gameLog',group='pitching' if role=='pitcher' else 'hitting',season='2025')
        response['payload'] = dict(stats=[dict(type=dict(displayName='gameLog'),
            group=dict(displayName='pitching' if role == 'pitcher' else 'hitting'), splits=[dict(player=dict(id=12345),
            season='2025', game=dict(gamePk=1234), date='2025-06-10', team=dict(id=1), opponent=dict(id=2), isHome=True,
            stat=dict(gamesPlayed=1, hits=2, runs=1, rbi=2, totalBases=5, homeRuns=1,
                strikeOuts=7, inningsPitched='5.2', earnedRuns=2))])])
        response['games'] = [dict(gamePk=1234, gameType='R', status=dict(abstractGameState='Final'))]
    artifact = dict(sport=sport, source=source, season=season, competition='Regular Season',
        observed_at='2026-06-20T12:00:00+00:00', responses=[response])
    mappings = [dict(sport=sport, source=source, athlete_id=athlete, player_id=PLAYER, verified=True, roles=[role],
        provenance='Invented test mapping only', identity_evidence='Independent fixture UUID association; no real person')]
    return deepcopy(artifact), mappings
