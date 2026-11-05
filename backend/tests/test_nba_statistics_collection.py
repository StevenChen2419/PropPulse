"""Collection contract tests with mocked nba_api, never provider HTTP."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('nba_collector',
    Path(__file__).resolve().parents[1] / 'scripts' / 'collect_nba_statistics.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.mapping = [dict(player_id='d41ec1f5-20f3-4930-9d8b-d001431b6ca7',
            nba_player_id='1630595', player_name='Fixture player',
            review_status='verified', provenance='Synthetic identity fixture')]
        self.plan = collector.build_plan(self.mapping, season='2025-26',
            competition='Regular Season', date_from='2025-10-01', date_to='2026-06-30')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'response.json'

    def test_plan_is_offline_exact_and_bounded(self):
        self.assertEqual(self.plan['request_budget'], 1)
        self.assertEqual(self.plan['common_parameters'], dict(Season='2025-26',
            SeasonType='Regular Season', LeagueID='00', DateFrom='10/01/2025', DateTo='06/30/2026'))
        self.assertEqual(self.plan['retries'], 0)
        with self.assertRaises(ValueError):
            collector.build_plan(self.mapping * 2, season='2025-26',
                competition='Regular Season', date_from='2025-10-01', date_to='2026-06-30')

    def test_mock_collection_writes_import_artifact_without_db(self):
        payload = {'resultSets': [{'name': 'PlayerGameLog', 'headers': [], 'rowSet': []}]}
        endpoint = SimpleNamespace(nba_response=SimpleNamespace(get_dict=lambda: payload))
        with patch('nba_api.stats.endpoints.playergamelog.PlayerGameLog', return_value=endpoint) as request:
            result = collector.collect(self.plan,
                approved_plan_sha256=collector.plan_digest(self.plan), output=self.output)
        self.assertEqual(json.loads(self.output.read_text()), result)
        self.assertEqual(result['responses'][0]['nba_player_id'], '1630595')
        self.assertEqual(result['responses'][0]['payload'], payload)
        self.assertEqual(request.call_args.kwargs['season_type_all_star'], 'Regular Season')
        self.assertEqual(request.call_args.kwargs['timeout'], 10)
        with self.assertRaises(FileExistsError):
            collector.collect(self.plan, approved_plan_sha256=collector.plan_digest(self.plan), output=self.output)

    def test_approval_and_unreviewed_identity_reject_before_transport(self):
        with patch('requests.sessions.Session.request', side_effect=AssertionError('HTTP forbidden')) as http:
            with self.assertRaises(ValueError):
                collector.collect(self.plan, approved_plan_sha256='wrong', output=self.output)
            candidate = deepcopy(self.plan)
            candidate['players'][0]['review_status'] = 'candidate'
            with self.assertRaises(ValueError):
                collector.collect(candidate, approved_plan_sha256=collector.plan_digest(candidate), output=self.output)
            http.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_failed_player_does_not_discard_or_stop_remaining_responses(self):
        mapping = self.mapping + [dict(self.mapping[0],
            player_id='a0c6430a-2ca3-4f7c-ac3c-a3d72345aadd', nba_player_id='1628369')]
        plan = collector.build_plan(mapping, season='2025-26',
            competition='Regular Season', date_from='2025-10-01', date_to='2026-06-30')
        payload = {'resultSets': [{'name': 'PlayerGameLog', 'headers': [], 'rowSet': []}]}
        endpoint = SimpleNamespace(nba_response=SimpleNamespace(get_dict=lambda: payload))
        with patch('nba_api.stats.endpoints.playergamelog.PlayerGameLog',
                   side_effect=[TimeoutError('do not expose routing details'), endpoint]) as request:
            result = collector.collect(plan, approved_plan_sha256=collector.plan_digest(plan),
                                       output=self.output)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result['failures'][0]['nba_player_id'], '1630595')
        self.assertEqual(result['failures'][0]['error'], 'TimeoutError')
        self.assertEqual(result['responses'][0]['nba_player_id'], '1628369')
        self.assertEqual(json.loads(self.output.read_text()), result)
        self.assertNotIn('routing details', self.output.read_text())

    def test_transport_bounds_and_pacing_apply_after_failure(self):
        import requests
        from nba_api.library.http import NBAHTTP
        mapping = self.mapping + [dict(self.mapping[0],
            player_id='a0c6430a-2ca3-4f7c-ac3c-a3d72345aadd', nba_player_id='1628369')]
        plan = collector.build_plan(mapping, season='2025-26',
            competition='Regular Season', date_from='2025-10-01', date_to='2026-06-30')
        payload = {'resultSets': [{'name': 'PlayerGameLog', 'headers': [], 'rowSet': []}]}
        response = requests.Response()
        response.status_code = 200
        response.url = plan['endpoint']
        response._content = json.dumps(payload).encode()
        response._content_consumed = True
        def transport(session, url, **kwargs):
            self.assertFalse(session.trust_env)
            self.assertEqual(kwargs['timeout'], 10)
            self.assertFalse(kwargs['allow_redirects'])
            self.assertFalse(kwargs.get('proxies'))
            if session.attempts == 1:
                raise requests.Timeout()
            return response
        with patch('requests.Session.get', autospec=True, side_effect=transport) as http, \
                patch.object(collector.time, 'monotonic', side_effect=[10, 10.5, 12.5]), \
                patch.object(collector.time, 'sleep') as sleep:
            result = collector.collect(plan, approved_plan_sha256=collector.plan_digest(plan),
                                       output=self.output)
        self.assertEqual(http.call_count, 2)
        self.assertEqual(result['request_count'], 2)
        sleep.assert_called_once_with(1.5)
        self.assertEqual(len(result['failures']), 1)
        self.assertEqual(len(result['responses']), 1)
        self.assertEqual(result['http_responses'][0]['nba_player_id'], '1628369')
        self.assertEqual(result['http_responses'][0]['status_code'], 200)
        self.assertEqual(json.loads(result['http_responses'][0]['body']), payload)
        self.assertIsNone(NBAHTTP._session)

    def test_empty_preseason_interval_has_no_requests(self):
        plan = collector.build_plan(self.mapping, season='2026-27', competition='Regular Season',
            date_from='2026-10-01', date_to='2026-10-18')
        self.assertEqual(plan['status'], 'no_games_yet')
        self.assertEqual(plan['request_budget'], 0)
        self.assertEqual(plan['requests'], [])

    def test_batch_skips_unresolved_identities(self):
        candidate = dict(self.mapping[0], player_id='a0c6430a-2ca3-4f7c-ac3c-a3d72345aadd',
                         nba_player_id='1628369', review_status='unresolved')
        plan = collector.build_plan(self.mapping + [candidate], season='2025-26',
            competition='Regular Season', date_from='2025-10-01', date_to='2026-06-30')
        self.assertEqual(plan['request_budget'], 1)
        self.assertEqual(plan['skipped'][0]['player_id'], candidate['player_id'])

    def test_streaming_byte_ceiling_and_access_denial_are_retained(self):
        import requests
        for status,body,limit in [(200,b'x'*100,16),(403,b'Access Denied',512000)]:
            with self.subTest(status=status):
                plan=deepcopy(self.plan);plan['max_response_bytes']=limit
                response=requests.Response();response.status_code=status;response.url=plan['endpoint']
                response._content=body;response._content_consumed=True
                path=self.output.with_name(str(status)+'.json')
                with patch('requests.Session.get',return_value=response) as transport:
                    result=collector.collect(plan,approved_plan_sha256=collector.plan_digest(plan),output=path)
                self.assertEqual(result['request_count'],1)
                self.assertEqual(result['responses'],[])
                self.assertEqual(result['http_responses'][0]['status_code'],status)
                self.assertTrue(transport.call_args.kwargs['stream'])
                if status==403:
                    self.assertEqual(result['failures'][0]['error'],'access_denied')
                    self.assertEqual(result['failures'][0]['http_status'],403)
                else:
                    self.assertEqual(result['response_bytes'],limit)
                    self.assertTrue(result['http_responses'][0]['truncated'])

    def test_opening_day_empty_scope_and_next_day_exact_sdk_parameters(self):
        from datetime import datetime
        clock=SimpleNamespace(now=lambda tz:datetime(2026,10,20,18,tzinfo=tz))
        with patch('app.services.nba_statistics_workflow.datetime',clock):
            empty=collector.build_plan(self.mapping,season='2026-27',competition='Regular Season',
                date_from='2026-10-20',date_to='2026-10-20')
        self.assertEqual(empty['request_budget'],0)
        with self.assertRaises(ValueError),patch('requests.Session.get') as transport:
            collector.collect(empty,approved_plan_sha256=collector.plan_digest(empty),output=self.output)
        transport.assert_not_called()
        clock=SimpleNamespace(now=lambda tz:datetime(2026,10,21,12,tzinfo=tz))
        with patch('app.services.nba_statistics_workflow.datetime',clock):
            ready=collector.build_plan(self.mapping,season='2026-27',competition='Regular Season',
                date_from='2026-10-20',date_to='2026-10-20')
        self.assertNotEqual(collector.plan_digest(empty),collector.plan_digest(ready))
        self.assertEqual(ready['requests'][0]['parameters'],dict(PlayerID='1630595',Season='2026-27',
            SeasonType='Regular Season',LeagueID='00',DateFrom='10/20/2026',DateTo='10/20/2026'))
        self.assertEqual(ready['max_response_bytes'],512000)
        self.assertEqual(ready['max_total_response_bytes'],4000000)


if __name__ == '__main__':
    unittest.main()
