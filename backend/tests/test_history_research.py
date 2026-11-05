"""Pure history fixtures and an isolated API; no providers/application database."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import get_db
from app.models import NBAEvidenceRecord, Player, Prop, PlayerGameLog, PropBookSnapshot
from app.routers.players import router
from app.services.trend_service import build_history_research


class HistoryWindowTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        self.start = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)

    def log(self, day, value=20, **kwargs):
        fields = dict(game_date=day, stats={'points': value}, sport='NBA', source='espn_nba',
                      external_game_id=str(day), opponent='Other', is_home=True)
        return NS(**{**fields, **kwargs})

    def history(self, logs, line=20):
        return build_history_research('NBA', 'points', line, 2027, logs,
                                      before_game=self.start, now=self.now)

    def test_previous_season_l5_l10_and_empty_current_season(self):
        result = self.history([self.log(datetime(2026, 5, day), day) for day in range(1, 13)])
        trends, meta = result['trends'], result['history']
        self.assertEqual(trends['l5']['games'], 5)
        self.assertEqual(trends['l10']['games'], 10)
        self.assertEqual(trends['l5']['seasons'], [2026])
        self.assertEqual(trends['l5']['season_scope'], 'previous_seasons')
        self.assertEqual(trends['season_window']['games'], 0)
        self.assertIsNone(trends['season_window']['hit_rate'])
        self.assertEqual(meta['previous_season_games'], 12)
        self.assertEqual(meta['current_season_games'], 0)
        self.assertEqual(meta['status'], 'available')
        self.assertEqual(result['results'][0]['value'], 12)

    def test_mixed_season_windows_do_not_contaminate_season(self):
        result = self.history([self.log(datetime(2026, 9, 20), 30), self.log(datetime(2026, 10, 20), 10)])
        self.assertEqual(result['trends']['l5']['season_scope'], 'mixed_seasons')
        self.assertEqual(result['trends']['l5']['seasons'], [2026, 2027])
        self.assertEqual(result['trends']['season_window']['games'], 1)
        self.assertEqual(result['trends']['season_window']['hits'], 0)
        self.assertTrue(result['history']['insufficient_l5'])
        self.assertTrue(result['history']['insufficient_l10'])

    def test_zero_push_missing_invalid_duplicate(self):
        day = datetime(2026, 5, 1)
        logs = [self.log(day, 0), self.log(day, 0), self.log(day + timedelta(days=1), 20),
                self.log(day + timedelta(days=2), None), self.log(day + timedelta(days=3), float('nan'))]
        result = self.history(logs)
        self.assertEqual(result['trends']['l5']['games'], 2)
        self.assertEqual(result['trends']['l5']['pushes'], 1)
        self.assertEqual(result['trends']['l5']['decisions'], 1)
        self.assertEqual(result['trends']['l5']['hit_rate'], 0)
        self.assertEqual(result['history']['excluded_counts'],
                         {'duplicate_game': 1, 'invalid_statistic': 1, 'missing_statistic': 1})
        self.assertEqual(len(logs), result['history']['eligible_games'] + sum(result['history']['excluded_counts'].values()))

    def test_dates_cutoff_offsets_and_synthetic_sources(self):
        logs = [self.log(self.start), self.log(self.start + timedelta(days=1)),
                self.log(self.now + timedelta(hours=1)), self.log(self.now - timedelta(hours=2)),
                self.log(datetime(2026, 5, 1), source='synthetic'),
                self.log(datetime(2026, 5, 2), source='espn_wnba'),
                self.log(datetime(2026, 5, 3), sport='WNBA')]
        result = self.history(logs)
        self.assertIsNone(result['trends'])
        self.assertEqual(result['history']['status'], 'excluded_history')
        self.assertEqual(result['history']['excluded_counts'],
                         {'at_or_after_prop': 2, 'future_game': 1, 'completion_unknown_today': 1,
                          'unsupported_source': 2, 'sport_mismatch': 1})
        offset = timezone(timedelta(hours=-5))
        result = self.history([self.log(datetime(2026, 5, 1, 22, tzinfo=offset)),
                               self.log(datetime(2026, 5, 2, 2), 10)])
        self.assertEqual(result['results'][0]['value'], 20)
        self.assertEqual(result['results'][0]['game_date'], '2026-05-02')

    def test_past_prop_excludes_results_after_start(self):
        result = build_history_research('NBA', 'points', 20, 2026,
            [self.log(datetime(2026, 5, 1)), self.log(datetime(2026, 5, 3))],
            before_game=datetime(2026, 5, 2), now=self.now)
        self.assertEqual(result['history']['eligible_games'], 1)
        self.assertEqual(result['history']['excluded_counts'], {'at_or_after_prop': 1})

    def test_preseason_and_unfinished_excluded(self):
        logs = [self.log(datetime(2026, 5, 1), stats={'points':20, 'season_type':'Pre-season'}),
                self.log(datetime(2026, 5, 2), stats={'points':20, 'completed':False}),
                self.log(self.now - timedelta(hours=1), stats={'points':20, 'completed':True})]
        result = self.history(logs)
        self.assertEqual(result['history']['eligible_games'], 1)
        self.assertEqual(result['history']['excluded_counts'], {'not_completed':1, 'preseason':1})
        self.assertIn('not separately identified', result['history']['competition_scope'])

    def test_no_history_missing_statistics_and_excluded_distinct(self):
        self.assertEqual(self.history([])['history']['status'], 'no_history')
        result = self.history([self.log(datetime(2026, 5, 1), stats={'assists':2})])
        self.assertEqual(result['history']['status'], 'no_valid_market_statistics')
        self.assertEqual(result['history']['valid_market_games'], 0)
        self.assertEqual(self.history([self.log(self.start)])['history']['status'], 'excluded_history')

    def test_all_pushes_have_no_decision_rate(self):
        result = self.history([self.log(datetime(2026, 5, 1))])
        self.assertIsNone(result['trends']['l5']['hit_rate'])
        self.assertEqual(result['trends']['l5']['games'], 1)


class ResearchApiTests(unittest.TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc)
        self.player = NS(id='player', sport='NBA')
        self.prop = NS(id='prop', player_id='player', is_active=True, odds_event_id='event',
            prop_type='points', line=20.5, sportsbook='FanDuel', opponent='Away', is_home=True,
            game_time=now + timedelta(days=2), book_offers=[NS(sportsbook='FanDuel', line=20.5,
                over_odds=-110, under_odds=-110, provider_observed_at=now-timedelta(minutes=1),
                ingested_at=now-timedelta(minutes=1))])
        self.logs = []
        self.db = MagicMock()
        def query(model):
            q = MagicMock()
            q.filter.return_value = q
            q.options.return_value = q
            q.order_by.return_value = q
            q.limit.return_value = q
            if model is Player: q.first.return_value = self.player
            elif model is Prop: q.all.return_value = [self.prop]
            elif model is PlayerGameLog: q.all.return_value = self.logs
            elif model is NBAEvidenceRecord: q.all.return_value = []
            elif model is PropBookSnapshot: q.first.return_value = None
            else: raise AssertionError('unexpected database model')
            return q
        self.db.query.side_effect = query
        app = FastAPI()
        app.include_router(router, prefix='/players')
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def test_prior_history_contract_and_offer_independence(self):
        day = datetime.now(timezone.utc) - timedelta(days=370)
        self.logs = [NS(game_date=day-timedelta(days=n), source='espn_nba', sport='NBA',
            stats={'points':10+n}, external_game_id=str(n), opponent='Away', is_home=True) for n in range(12)]
        response = self.client.get('/players/player/research')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['trends']['l5']['games'], 5)
        self.assertEqual(body['trends']['l10']['games'], 10)
        self.assertEqual(body['trends']['season_window']['games'], 0)
        self.assertEqual(body['history']['eligible_games'], 12)
        self.assertEqual(body['selected_prop']['over_odds'], -110)
        self.assertNotIn('No historical results for this prop type', body['message'] or '')
        self.db.commit.assert_not_called()

    def test_empty_history_does_not_remove_selected_offer(self):
        body = self.client.get('/players/player/research').json()
        self.assertIsNone(body['trends'])
        self.assertEqual(body['history']['status'], 'no_history')
        self.assertEqual(body['selected_prop']['over_odds'], -110)
        self.assertTrue(body['selected_prop']['actionable'])
