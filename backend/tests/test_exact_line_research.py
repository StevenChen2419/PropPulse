"""Invented offline source records; exact comparisons and scoped appearances."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
import unittest

from app.services.exact_line_research import build_exact_line_research, MARKET_METRICS
from app.services.sports_statistics import normalize_artifact
from app.services.nba_api_provider import normalize_player_statistics
from sports_statistics_fixture import fixture
from nba_statistics_fixture import statistics_fixture

NOW = datetime(2026, 10, 21, 18, tzinfo=timezone.utc)


def rows_for(sport, role=None, values=(3, 2, 1, None)):
    if sport == 'NBA':
        payload, crosswalk, season, observed = statistics_fixture(NOW)
        records = normalize_player_statistics(payload, observed_at=observed, crosswalk=crosswalk,
                                              season=season, competition='Regular Season')
        seed = records[0]
    else:
        artifact, mappings = fixture(sport, role)
        season = artifact['season']
        seed = normalize_artifact(artifact, mappings, season=season)['records'][0]
    player = NS(id=seed['player_id'], sport=sport, position=None)
    rows = []
    for i, value in enumerate(values):
        row = deepcopy(seed)
        row['external_game_id'] += f'-invented-{i}'
        row['game_date'] -= timedelta(days=i)
        row['stats'].update({key: value for metrics in MARKET_METRICS[sport].values() for key in metrics})
        rows.append(NS(**row))
    return player, rows, season


class ExactLineResearchTests(unittest.TestCase):
    def analyze(self, sport='WNBA', market='points', line=2, side='over', role=None, values=(3,2,1,None), **changes):
        player, rows, season = rows_for(sport, role, values)
        return build_exact_line_research(player, rows, market=market, line=line, side=side,
                                         season=season, now=NOW, **changes)

    def test_over_under_push_missing_actual_samples(self):
        over=self.analyze(); under=self.analyze(side='under')
        sample=over['l5']
        self.assertEqual([g['outcome'] for g in over['games']], ['over','push','under','missing'])
        self.assertEqual((sample['appearances'],sample['valid_samples'],sample['missing_samples']), (4,3,1))
        self.assertEqual((sample['hits'],sample['losses'],sample['pushes']), (1,1,1))
        self.assertEqual((sample['raw_hit_rate'],sample['settled_hit_rate']), (1/3,1/2))
        self.assertEqual(under['l5']['hits'],1)
        self.assertEqual(over['l10'],over['season_window'])

    def test_all_sport_markets_and_roles(self):
        for sport, markets in MARKET_METRICS.items():
            for market in markets:
                role = ('goalie' if market=='saves' else 'skater') if sport=='NHL' else (
                    'pitcher' if market in {'strikeouts','outs_recorded'} else 'batter') if sport=='MLB' else None
                with self.subTest(sport=sport,market=market):
                    result=self.analyze(sport,market,role=role)
                    self.assertEqual(result['status'],'available')
                    self.assertEqual(result['l5']['missing_samples'],1)

    def test_combinations_require_all_inputs_and_no_arbitrary_rounding(self):
        player,rows,season=rows_for('WNBA',values=(1,1,1,1))
        rows[0].stats.update(points=1,rebounds=2,assists=3)
        rows[1].stats['assists']=None
        result=build_exact_line_research(player,rows,market='pra',line=6,season=season,now=NOW)
        self.assertEqual(result['games'][0]['outcome'],'push')
        self.assertEqual(result['games'][1]['outcome'],'missing')
        self.assertEqual(self.analyze(line=2.5)['l5']['pushes'],0)
        self.assertEqual(self.analyze(line=2.00000001)['games'][1]['outcome'],'under')
        nfl=self.analyze('NFL','rush_reception_yds',line=4,values=(2,1,None))
        self.assertEqual(nfl['games'][0]['outcome'],'push')

    def test_recent_windows_select_appearances_before_missing_values(self):
        result=self.analyze(values=(None,)*5+(3,)*7)
        self.assertEqual(result['l5']['valid_samples'],0)
        self.assertIsNone(result['l5']['raw_hit_rate'])
        self.assertEqual((result['l10']['appearances'],result['l10']['valid_samples']),(10,5))
        self.assertEqual(result['season_window']['appearances'],12)
        self.assertEqual(len(result['games']),10)

    def test_role_separation_unsupported_and_empty(self):
        for sport,market,role in [('NHL','saves','skater'),('NHL','goals','goalie'),
                                  ('MLB','strikeouts','batter'),('MLB','hits','pitcher')]:
            self.assertEqual(self.analyze(sport,market,role=role)['status'],'unsupported_role')
        self.assertEqual(self.analyze(market='invented_market')['status'],'unsupported_market')
        self.assertEqual(self.analyze(values=())['status'],'no_recorded_games')
        self.assertEqual(self.analyze(values=(None,))['status'],'missing_metric')

    def test_identity_season_competition_dates_observation_and_duplicates(self):
        player,rows,season=rows_for('NFL',values=(3,3,3,3,3,3))
        rows[1].player_id='wrong-local-player'
        rows[2].stats['_research']['season']='2024'
        rows[3].stats['_research']['competition']='Playoffs'
        rows[4].stats['_research']['observed_at']=(NOW+timedelta(days=1)).isoformat()
        rows[5].game_date=NOW+timedelta(days=1)
        result=build_exact_line_research(player,rows+[rows[0]],market='pass_yds',line=2,season=season,now=NOW)
        self.assertEqual(result['season_window']['appearances'],1)
        self.assertEqual(result['competition'],'Regular Season')
        before=build_exact_line_research(player,rows,market='pass_yds',line=2,season=season,
                                         now=NOW,reference=rows[0].game_date)
        self.assertEqual(before['season_window']['appearances'],0)

    def test_nba_reviewed_source_and_legacy_isolation(self):
        player,rows,season=rows_for('NBA')
        rows[1].stats['_nba']['competition']='Playoffs'
        rows[2].source='espn_nba'
        rows[3].stats['_nba']['reviewed_crosswalk']=False
        result=build_exact_line_research(player,rows,market='points',line=2,season=season,now=NOW)
        self.assertEqual(result['season_window']['appearances'],1)
        self.assertEqual(result['source'],'nba_com_stats')
        empty=build_exact_line_research(player,rows,market='points',line=2,season='2025-26',now=NOW)
        self.assertEqual(empty['season_window']['appearances'],0)

    def test_opponents_use_verified_source_ids_and_same_market_line(self):
        player,rows,season=rows_for('NHL')
        rows[1].stats['_research']['opponent_id']='verified-other'
        rows[2].stats['_research']['opponent_id']=None
        for row in rows: row.opponent='Same misleading text'
        result=build_exact_line_research(player,rows,market='shots_on_goal',line=2,side='under',season=season,now=NOW)
        self.assertIsNone(result['current_opponent_id'])
        self.assertEqual(sum(o['season_window']['appearances'] for o in result['opponents']),3)
        self.assertEqual(len(result['opponents']),2)


def browser_fixtures():
    result=[]
    for sport,role,market in [('NBA',None,'points'),('WNBA',None,'points'),('NHL','skater','shots_on_goal'),
            ('NHL','goalie','saves'),('NFL',None,'pass_yds'),('MLB','batter','hits'),('MLB','pitcher','outs_recorded')]:
        player,rows,season=rows_for(sport,role)
        for line,side in ([(2,'over'),(2.5,'under')] if sport=='WNBA' else [(2,'over')]):
            exact=build_exact_line_research(player,rows,market=market,line=line,side=side,season=season,now=NOW)
            exact['selection']=dict(sportsbook='FanDuel' if line==2 else 'DraftKings',line=line,side=side,
                actionable=False,availability='expired',odds=None,provider_observed_at='2026-10-20T00:00:00Z')
            exact['offer_options']=[dict(sportsbook='FanDuel',line=2),dict(sportsbook='DraftKings',line=2.5)]
            exact['limitations'].append('Invented offline fixture; not real sports coverage.')
            result.append(dict(sport=sport,role=role,exact=exact))
    return result


if __name__=='__main__': unittest.main()
