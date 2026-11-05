"""Unified refresh uses invented artifacts, blocked HTTP and isolated SQLite only."""
from argparse import Namespace
from contextlib import redirect_stdout, nullcontext
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import refresh_all_sports as refresh
from scripts import collect_nhl_statistics as nhl
from scripts import refresh_sports_odds as odds
from sports_statistics_fixture import fixture
from app.services.sports_statistics import normalize_artifact


class UnifiedRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = Namespace(sports=['wnba'], include=['statistics'], scope=None, coverage=None,
            database_target='localhost:5432/proppulse', max_requests=10, max_credits=0,
            quota_reserve=50, output_dir=self.root/'run')
        from sqlalchemy.engine import Engine
        for target in ('requests.sessions.Session.request', 'httpx.HTTPTransport.handle_request',
                       'httpx.AsyncHTTPTransport.handle_async_request'):
            block = patch(target, side_effect=AssertionError('No HTTP'))
            block.start(); self.addCleanup(block.stop)
        block = patch.object(Engine, 'connect', side_effect=AssertionError('No DB'))
        block.start(); self.addCleanup(block.stop)

    def write(self, name, value):
        path = self.root/name
        path.write_text(json.dumps(value), encoding='utf-8')
        return str(path)

    def artifact_scope(self, sport='WNBA'):
        artifact, mappings = fixture(sport)
        return dict(action='artifact', season=artifact['season'],
            mapping=self.write(sport+'-mapping.json', mappings),
            artifacts=[self.write(sport+'-artifact.json', artifact)])

    def plan(self, specs):
        self.args.scope = self.write('scope.json', dict(statistics=specs))
        return refresh.build_plan(self.args)

    def retained_odds(self):
        return dict(database_target=self.args.database_target,
            quota=dict(remaining=100, observed_at=datetime.now(timezone.utc).isoformat(), evidence='Invented quota receipt'),
            sports=dict(basketball_wnba=dict(access='accessible', evidence='Invented event market receipt',
                markets=['player_points'], events=[dict(id='abc123', home_team='Home', away_team='Away',
                    commence_time=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())])))

    def test_sports_all_deduplication_and_invalid_selection(self):
        self.assertEqual(refresh.select_sports(['all']), list(refresh.SPORTS))
        self.assertEqual(refresh.select_sports(['nba','nba','nhl']), ['nba','nhl'])
        for values in ([], ['all','nba'], ['soccer']):
            with self.assertRaises(ValueError): refresh.select_sports(values)

    def test_artifact_preview_no_db_no_http_and_observed_coverage(self):
        spec = self.artifact_scope()
        plan = self.plan(dict(wnba=spec))
        op = plan['statistics'][0]
        self.assertEqual(op['status'], 'ready')
        self.assertEqual(op['source'], 'wehoop_wnba_stats')
        self.assertEqual(op['validated_game_logs'], 1)
        self.assertEqual(op['statistics_last_observed'], '2026-06-20T12:00:00+00:00')
        self.assertIn('2025-06-10', op['latest_completed_game_represented'])
        self.assertEqual(op['coverage_complete'], 'unknown')
        self.assertEqual(plan['provider_request_upper_bound'], 0)
        self.assertFalse(self.args.output_dir.exists())

    def test_all_source_selection_and_independent_invalid_sport(self):
        self.args.sports = ['wnba','nhl','nfl','mlb']
        specs = {s:self.artifact_scope(s.upper()) for s in self.args.sports}
        specs['nfl']['mapping'] = str(self.root/'absent.json')
        plan = self.plan(specs)
        self.assertEqual([o['status'] for o in plan['statistics']], ['ready','ready','failed','ready'])
        self.assertEqual([o.get('source') for o in plan['statistics'] if o['status']=='ready'],
                         ['wehoop_wnba_stats','nhl_web','mlb_stats_api'])

    def test_nba_artifact_preview_uses_offline_batch_and_preserves_season(self):
        from test_nba_statistics_workflow import fixture as nba_fixture, SCOPE
        mappings, artifact = nba_fixture()
        self.args.sports=['nba']
        spec=dict(action='artifact', **SCOPE, mapping=self.write('nba-mapping.json',mappings),
                  artifacts=[self.write('nba-artifact.json',artifact)])
        from app.config import settings
        with patch.object(settings,'DATABASE_URL','postgresql://fixture@localhost:5432/proppulse'):
            plan=self.plan(dict(nba=spec))
        op=plan['statistics'][0]
        self.assertEqual(op['status'],'ready')
        self.assertEqual(op['validated_game_logs'],24)
        self.assertEqual(op['season'],'2025-26')
        self.assertEqual(op['approval_scope']['database_target']['username'],'fixture')

    def test_nba_no_completed_dates_is_not_an_independent_sport_failure(self):
        from test_nba_statistics_workflow import fixture as nba_fixture
        mappings,_=nba_fixture()
        self.args.sports=['nba','wnba']
        spec=dict(action='collect',season='2026-27',date_from='2026-10-20',date_to='2026-10-20',
            mapping=self.write('nba-reviewed.json',mappings),output=str(refresh.RUNS/'never-collected-nba-current.json'))
        clock=SimpleNamespace(now=lambda tz:datetime(2026,10,20,12,tzinfo=tz))
        with patch('app.services.nba_statistics_workflow.datetime',clock):
            plan=self.plan(dict(nba=spec,wnba=self.artifact_scope()))
        self.assertEqual(plan['statistics'][0]['status'],'no_games_yet')
        self.assertEqual(plan['statistics'][0]['provider_requests'],0)
        self.assertEqual(plan['statistics'][1]['status'],'ready')
        with patch.object(refresh,'validate_database'),patch.object(refresh,'execute_statistics',
                return_value=dict(status='imported',actual_api_requests=0)) as execute:
            report=refresh.execute(plan,refresh.statistics.digest(plan),self.args.output_dir)
        self.assertEqual(execute.call_count,1)
        self.assertEqual(report['status'],'finished')
        self.assertEqual(report['operations'][0]['status'],'no_games_yet')

    def test_csv_payload_change_invalidates_parent_approval(self):
        spec=self.artifact_scope()
        artifact=refresh.read(spec['artifacts'][0])
        row=artifact['responses'][0].pop('payload')[0]
        import csv
        csv_path=self.root/'release.csv'
        def save():
            with csv_path.open('w',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=list(row)); writer.writeheader();writer.writerow(row)
        save()
        artifact['responses'][0]['payload_file']='release.csv'
        Path(spec['artifacts'][0]).write_text(json.dumps(artifact))
        before=self.plan(dict(wnba=spec))
        self.assertEqual(before['statistics'][0]['status'],'ready')
        row['pts']=9;save()
        after=refresh.build_plan(self.args)
        self.assertNotEqual(refresh.statistics.digest(before),refresh.statistics.digest(after))

    def test_no_database_write_with_redirected_or_wrong_target(self):
        from app.config import settings
        with patch.object(settings,'DATABASE_URL','postgresql://fixture@localhost:5432/proppulse'), \
             patch.object(settings,'ENVIRONMENT','development'),patch.object(settings,'LIVE_REFRESH_ENABLED',False):
            with self.assertRaises(ValueError): refresh.validate_database('other:5432/proppulse')
            with patch.dict('os.environ',dict(PGHOST='other')):
                with self.assertRaises(ValueError): refresh.validate_database('localhost:5432/proppulse')

    def test_unreviewed_identity_rejected_offline(self):
        spec = self.artifact_scope()
        mapping = json.loads(Path(spec['mapping']).read_text())
        mapping[0]['verified'] = False
        Path(spec['mapping']).write_text(json.dumps(mapping))
        self.assertEqual(self.plan(dict(wnba=spec))['statistics'][0]['status'], 'failed')

    def test_dataset_collection_explicitly_unsupported(self):
        self.args.sports = ['wnba','nfl','mlb']
        plan = self.plan({s:dict(action='collect') for s in self.args.sports})
        self.assertTrue(all(o['status']=='unsupported' for o in plan['statistics']))
        self.assertEqual(plan['provider_request_upper_bound'], 0)

    def test_nhl_verified_roles_exact_collection_and_combined_ceiling(self):
        self.args.sports = ['nhl']
        _, mappings = fixture('NHL', 'goalie')
        spec = dict(action='collect', season='2025-26', mapping=self.write('nhl.json', mappings),
            output=str(refresh.RUNS/'unified-test-never-created.json'))
        plan = self.plan(dict(nhl=spec))
        op = plan['statistics'][0]
        self.assertEqual(op['provider_requests'], 2)
        self.assertEqual(op['collection_plan']['players'][0]['roles'], ['goalie'])
        self.assertEqual(op['collection_plan']['requests'][1]['path'], '/v1/player/12345/game-log/20252026/2')
        self.args.max_requests = 1
        with self.assertRaises(ValueError): refresh.build_plan(self.args)
        with self.assertRaises(ValueError): nhl.collect(op['collection_plan'], approved_plan_sha256='wrong', output=self.root/'no.json')
        self.assertFalse((self.root/'no.json').exists())

    def test_wrong_digest_never_imports_or_validates_database(self):
        plan = self.plan(dict(wnba=self.artifact_scope()))
        with patch.object(refresh,'execute_statistics') as imports, patch.object(refresh,'validate_database') as db:
            with self.assertRaises(ValueError): refresh.execute(plan, 'wrong', self.args.output_dir)
            imports.assert_not_called(); db.assert_not_called()
        self.assertFalse(self.args.output_dir.exists())

    def test_artifact_mutation_changes_digest(self):
        spec = self.artifact_scope()
        before = self.plan(dict(wnba=spec))
        data = json.loads(Path(spec['artifacts'][0]).read_text())
        data['responses'][0]['payload'][0]['pts'] = 8
        Path(spec['artifacts'][0]).write_text(json.dumps(data))
        after = refresh.build_plan(self.args)
        self.assertNotEqual(refresh.statistics.digest(before), refresh.statistics.digest(after))

    def test_approved_child_scope_delegated_exactly_and_failures_independent(self):
        self.args.sports = ['wnba','nhl']
        plan = self.plan({s:self.artifact_scope(s.upper()) for s in self.args.sports})
        attempted = []
        def run(op, folder):
            attempted.append(op['sport'])
            if op['sport']=='wnba': raise ValueError('Invented failure')
            return dict(status='imported', actual_api_requests=0, new_game_logs=1, updated_game_logs=0,
                        unchanged_game_logs=0, rejected_game_logs=0, database_writes=1)
        with patch.object(refresh, 'validate_database'), patch.object(refresh, 'execute_statistics', side_effect=run):
            result = refresh.execute(plan, refresh.statistics.digest(plan), self.args.output_dir)
        self.assertEqual(attempted, ['wnba','nhl'])
        self.assertEqual([o['status'] for o in result['operations']], ['failed','imported'])
        with self.assertRaises(FileExistsError), patch.object(refresh,'validate_database'):
            refresh.execute(plan, refresh.statistics.digest(plan), self.args.output_dir)
        op = plan['statistics'][1]
        def importer(argv):
            self.assertEqual(argv[:-2], op['command'])
            self.assertEqual(argv[-2], '--import-approved')
            self.assertEqual(refresh.read(argv[-1]), op['approval_scope'])
            print(json.dumps(dict(counts=dict(new=1,updated=0,unchanged=0,rejected=0))))
            return 0
        with patch.object(refresh.statistics, 'main', side_effect=importer):
            actual = refresh.execute_statistics(op, self.args.output_dir)
        self.assertEqual(actual['new_game_logs'],1)

    def test_quota_ceiling_reserve_age_and_unknown_fail_closed(self):
        self.args.include = ['odds']; self.args.max_credits = 1
        retained = self.retained_odds()
        self.args.coverage = self.write('odds.json', retained)
        plan = refresh.build_plan(self.args)
        self.assertEqual(plan['sportsbook_credit_upper_bound'],1)
        self.assertEqual(plan['provider_request_upper_bound'],3)
        self.assertIsNone(plan['odds_execution_blocker'])
        for quota in ({}, retained['quota'] | dict(remaining=50),
                      retained['quota'] | dict(observed_at=(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat())):
            self.args.coverage = self.write('odds.json', retained | dict(quota=quota))
            blocked = refresh.build_plan(self.args)
            with patch.object(refresh.odds, 'execute') as execute:
                folder = self.root/str(len(list(self.root.iterdir())))
                blocked['run_directory']=str(folder)
                report = refresh.execute(blocked, refresh.statistics.digest(blocked), folder)
                execute.assert_not_called()
            self.assertEqual(report['odds']['status'], 'skipped')
        self.args.max_credits = 0
        with self.assertRaises(ValueError): refresh.build_plan(self.args)

    def test_odds_exact_approval_and_summary_accounting(self):
        self.args.include=['odds']; self.args.max_credits=1
        self.args.coverage=self.write('odds.json',self.retained_odds())
        plan=refresh.build_plan(self.args)
        report=dict(status='finished', provider_requests_consumed=3, credits_accounted=1, credits_consumed=1,
            quota_remaining=99, sports=dict(basketball_wnba=dict(outcome='completed', events_successfully_processed=1,
                sportsbook_offers_saved=5, market_requests_made=1)))
        with patch.object(refresh,'validate_database'), patch.object(refresh.odds,'execute',return_value=report) as execute:
            result=refresh.execute(plan,refresh.statistics.digest(plan),self.args.output_dir)
        self.assertEqual(execute.call_args.kwargs,dict(allow_player_changes=False,strict_scope=True))
        self.assertEqual(result['actual_api_requests'],3)
        self.assertEqual(result['credits_consumed'],1)
        self.assertEqual(result['confirmed_credits_remaining'],99)
        self.assertEqual(result['operations'][0]['offers_inserted_or_updated'],5)

    def test_default_cli_stores_offline_summary_only(self):
        with patch.object(refresh,'RUNS',self.root), redirect_stdout(io.StringIO()) as stdout:
            code=refresh.main(['--sports','all','--output-dir',str(self.root/'cli')])
        self.assertEqual(code,0)
        result=json.loads(stdout.getvalue())
        self.assertEqual(result['database_writes'],0)
        self.assertEqual(result['actual_api_requests'],0)
        self.assertEqual(result['mode'],'dry-run')
        self.assertTrue(Path(result['summary_file']).exists())


class StrictOddsTests(unittest.TestCase):
    def test_missing_live_quota_headers_stop_further_requests(self):
        from scripts import fetch_odds as importer
        coverage_doc=dict(database_target='testhost:5432/proppulse_test_phase9', sports=dict(
            basketball_wnba=dict(access='accessible',evidence='Invented receipt',markets=['player_points'],
                events=[dict(id='abc',home_team='Home',away_team='Away',commence_time='2099-01-01T00:00:00Z')])))
        plan=odds.plan_refresh(coverage_doc,['basketball_wnba'],max_credits=1)
        def verify(client,statuses):
            importer.get(client,'/sports',{})
            self.assertTrue(importer.ACTIVE_BUDGET.stopped)
            self.assertIsNone(importer.ACTIVE_BUDGET.remaining)
            return False
        with patch.object(importer,'engine',SimpleNamespace(url='postgresql://test@testhost:5432/proppulse_test_phase9')), \
             patch.object(odds,'odds_ingestion_lock',return_value=nullcontext(True)), \
             patch.object(importer,'get',return_value=(200,[],{})), \
             patch.object(importer,'verify_key_and_sports',side_effect=verify), \
             patch.object(importer,'persist_sports'), patch.object(importer,'finalize_sport_status'), \
             patch.object(importer,'write_status'), patch.object(importer,'aggregate_status',return_value={}):
            result=odds.execute(plan,odds.plan_digest(plan),strict_scope=True,allow_player_changes=False)
        self.assertEqual(result['credits_consumed'],'unknown')
        self.assertEqual(result['budget_stop_reason'],'unconfirmed_quota')

    def test_out_of_scope_request_is_rejected_before_transport(self):
        from scripts import fetch_odds as importer
        plan=odds.plan_refresh(dict(database_target='testhost:5432/test',sports=dict(
            basketball_wnba=dict(access='accessible',evidence='Invented receipt',markets=['player_points'],
                events=[dict(id='abc',home_team='H',away_team='A',commence_time='2099-01-01T00:00:00Z')]))),
            ['basketball_wnba'],max_credits=1)
        def verify(client,statuses):
            importer.get(client,'/sports/basketball_wnba/events/unapproved/odds',dict(markets='player_points',regions='us'))
        with patch.object(importer,'engine',SimpleNamespace(url='postgresql://test@testhost:5432/test')), \
             patch.object(odds,'odds_ingestion_lock',return_value=nullcontext(True)), \
             patch.object(importer,'get') as transport,patch.object(importer,'verify_key_and_sports',side_effect=verify), \
             patch.object(importer,'persist_sports') as persist:
            result=odds.execute(plan,odds.plan_digest(plan),strict_scope=True,allow_player_changes=False)
        transport.assert_not_called();persist.assert_not_called()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['provider_requests_consumed'],0)


class NHLCollectionTests(unittest.TestCase):
    def test_verified_skater_and_goalie_transport_and_offline_normalization(self):
        import httpx
        for role,position in [('skater','C'),('goalie','G')]:
            with self.subTest(role=role),tempfile.TemporaryDirectory() as folder:
                source,mappings=fixture('NHL',role)
                plan=nhl.build_plan(mappings,season='2025-26')
                requested=[]
                def handle(request):
                    requested.append(request.url.path)
                    payload=source['responses'][0]['payload']
                    if request.url.path.endswith('/landing'):
                        payload=dict(playerId=12345,position=position,seasonTotals=[dict(season=20252026,
                            gameTypeId=2,leagueAbbrev='NHL',gamesPlayed=1)])
                    return httpx.Response(200,json=payload)
                client=httpx.Client(transport=httpx.MockTransport(handle))
                with patch.object(httpx,'Client',return_value=client):
                    artifact=nhl.collect(plan,approved_plan_sha256=nhl.plan_digest(plan),output=Path(folder)/'artifact.json')
                self.assertEqual(len(requested),2)
                self.assertEqual(artifact['request_count'],2)
                self.assertEqual(artifact['failures'],[])
                self.assertEqual(len(artifact['profiles']),1)
                rows=normalize_artifact(artifact,mappings,season='2025-26')['records']
                self.assertEqual(len(rows),1)
                metric='saves' if role=='goalie' else 'goals'
                self.assertIn(metric,rows[0]['stats'])

    def test_wrong_profile_identity_prevents_game_log_request_and_replay(self):
        import httpx
        _,mappings=fixture('NHL')
        plan=nhl.build_plan(mappings,season='2025-26')
        requested=[]
        def handle(request):
            requested.append(request.url.path)
            return httpx.Response(200,json=dict(playerId=999,position='C',seasonTotals=[]))
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'artifact.json'
            client=httpx.Client(transport=httpx.MockTransport(handle))
            with patch.object(httpx,'Client',return_value=client):
                artifact=nhl.collect(plan,approved_plan_sha256=nhl.plan_digest(plan),output=output)
                with self.assertRaises(FileExistsError):
                    nhl.collect(plan,approved_plan_sha256=nhl.plan_digest(plan),output=output)
        self.assertEqual(len(requested),1)
        self.assertEqual(artifact['responses'],[])
        self.assertEqual(artifact['request_count'],1)
        self.assertEqual(artifact['failures'][-1]['reason'],'profile_not_verified')


if __name__ == '__main__':
    unittest.main()
