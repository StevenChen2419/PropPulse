"""Manual refresh tests: synthetic responses, mocked transport/DB, no real calls."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import refresh_nba_statistics as refresh
from test_nba_statistics_workflow import fixture, SCOPE


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.mappings, artifact = fixture()
        self.mapping = self.folder / 'mapping.json'
        self.mapping.write_text(json.dumps(self.mappings), encoding='utf-8')
        self.artifact = self.folder / 'artifact.json'
        self.artifact.write_text(json.dumps(artifact), encoding='utf-8')
        self.args = ['--season', '2025-26', '--from-date', SCOPE['date_from'],
            '--to-date', SCOPE['date_to'], '--all-verified', '--mapping', str(self.mapping),
            '--output-dir', str(self.folder / 'run')]

    def invoke(self, extra=(), args=None):
        stdout = io.StringIO()
        with patch('requests.sessions.Session.request', side_effect=AssertionError('No HTTP')), \
                patch('sqlalchemy.create_engine', side_effect=AssertionError('No DB')), redirect_stdout(stdout):
            code = refresh.main((args or self.args) + list(extra))
        return code, json.loads(stdout.getvalue())

    def test_default_and_explicit_dry_run_are_offline_bounded_plans(self):
        for extra in ([], ['--dry-run']):
            code, result = self.invoke(extra)
            self.assertEqual(code, 0)
            self.assertEqual(result['status'], 'collection_approval_required')
            self.assertEqual(result['plan']['request_budget'], 2)
            self.assertEqual(result['plan']['retries'], 0)
            self.assertEqual(result['plan']['timeout_seconds'], 10)
            self.assertEqual(len(result['plan_sha256']), 64)
        self.assertFalse((self.folder / 'run').exists())

    def test_preopening_returns_no_games_without_provider_or_db(self):
        args = self.args.copy()
        args[1] = '2026-27'
        args[3], args[5] = '2026-10-20', '2026-10-20'
        with patch('app.services.nba_statistics_workflow.datetime', SimpleNamespace(now=lambda tz: datetime(2026, 10, 19, tzinfo=tz))):
            code, result = self.invoke(args=args)
            self.assertEqual(code, 0)
            self.assertEqual(result['status'], 'no_games_yet')
            self.assertEqual(result['provider_requests'], 0)
            code, result = self.invoke(['--collect-approved', 'old-authorization'], args=args)
            self.assertEqual(code, 1)
            self.assertEqual(result['status'], 'rejected')

    def test_current_season_plan_after_opening_has_exact_scope_and_player_selection(self):
        args = self.args.copy()
        args[1], args[3], args[5] = '2026-27', '2026-10-20', '2026-10-22'
        args[6:7] = ['--players', self.mappings[0]['player_id']]
        clock = SimpleNamespace(now=lambda tz: datetime(2026, 10, 23, tzinfo=tz))
        with patch('app.services.nba_statistics_workflow.datetime', clock):
            code, result = self.invoke(args=args)
        self.assertEqual(code, 0)
        plan = result['plan']
        self.assertEqual(plan['request_budget'], 1)
        self.assertEqual(plan['common_parameters'], dict(Season='2026-27', SeasonType='Regular Season',
            LeagueID='00', DateFrom='10/20/2026', DateTo='10/22/2026'))
        self.assertEqual(plan['players'][0]['nba_player_id'], self.mappings[0]['nba_player_id'])

    def test_unresolved_players_are_skipped_and_wrong_approval_never_collects(self):
        self.mappings[1]['review_status'] = 'unresolved'
        self.mapping.write_text(json.dumps(self.mappings), encoding='utf-8')
        _, result = self.invoke()
        self.assertEqual(len(result['plan']['skipped']), 1)
        with patch.object(refresh.collector, 'collect') as collect:
            code, result = self.invoke(['--collect-approved', 'incorrect'])
            self.assertEqual(code, 1)
            collect.assert_not_called()

    def test_approved_collection_validates_offline_without_import(self):
        _, result = self.invoke()
        artifact = json.loads(self.artifact.read_text()) | {'request_count': 2}
        def collect(plan, *, approved_plan_sha256, output):
            Path(output).write_text(json.dumps(artifact), encoding='utf-8')
            return artifact
        with patch.object(refresh.collector, 'collect', side_effect=collect), \
                patch.object(refresh.importer, 'main') as importer:
            code, result = self.invoke(['--collect-approved', result['plan_sha256']])
        self.assertEqual(code, 0)
        self.assertEqual(result['normalized_rows'], 24)
        self.assertEqual(result['request_count'], 2)
        importer.assert_not_called()

    def test_preview_consolidates_and_writes_only_proposed_approval(self):
        scope = dict(artifact_sha256='a'*64, mapping_sha256='b'*64,
            database_target={'host': 'localhost', 'database': 'proppulse'},
            player_ids=[p['player_id'] for p in self.mappings])
        def importer(argv):
            self.assertNotIn('--execute', argv)
            print(json.dumps(dict(players=[dict(added=2, updated=1, unchanged=3, records=6)], approval_scope=scope)))
            return 0
        with patch.object(refresh.importer, 'main', side_effect=importer):
            code, result = self.invoke(['--artifact', str(self.artifact)])
        self.assertEqual(code, 0)
        self.assertEqual(result['totals'], dict(added=2, updated=1, unchanged=3, records=6, rejected=0))
        self.assertEqual(json.loads(Path(result['proposed_approval_file']).read_text()), scope)

    def test_import_delegates_exact_approval_and_never_collects(self):
        approval = self.folder / 'approval.json'
        def importer(argv):
            self.assertIn('--execute', argv)
            self.assertEqual(argv[argv.index('--approval') + 1], str(approval))
            print(json.dumps(dict(players=[], mode='execute')))
            return 0
        with patch.object(refresh.importer, 'main', side_effect=importer), \
                patch.object(refresh.collector, 'collect') as collect:
            code, result = self.invoke(['--artifact', str(self.artifact), '--import-approved', str(approval)])
        self.assertEqual(code, 0)
        collect.assert_not_called()

    def test_import_failure_does_not_create_approval_or_continue(self):
        with patch.object(refresh.importer, 'main', return_value=1):
            # Empty delegated diagnostic still needs valid structured reporting.
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = refresh.main(self.args + ['--artifact', str(self.artifact)])
        self.assertEqual(code, 1)
        self.assertFalse((self.folder / 'run/proposed-import-approval.json').exists())


if __name__ == '__main__':
    unittest.main()
