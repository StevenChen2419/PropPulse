"""CLI guards use mocked engines/executor, never the configured database."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import link_verified_event as cli


class VerifiedLinkageCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "report.json"
        from scripts import prepare_event_links
        self.patches = [patch.object(prepare_event_links,"MANIFEST_DIRECTORY",self.root),
            patch.object(cli,"settings",SimpleNamespace(ENVIRONMENT="development",LIVE_REFRESH_ENABLED=False,
                DATABASE_URL="postgresql://fake:fake@localhost:5432/proppulse")),
            patch.object(cli,"load_reviewed_files",return_value={}),
            patch.object(cli,"create_engine"),
            patch.object(cli,"run_verified_linkage",return_value={"mode":"dry_run","status":"completed",
                "transaction_outcome":"read_only_rolled_back","committed":{"events_created":0,"links_created":0},
                "rejections":[]})]
        self.mocks = [p.start() for p in self.patches]
        for p in self.patches:self.addCleanup(p.stop)

    def invoke(self,*args):
        with redirect_stdout(io.StringIO()) as stdout,redirect_stderr(io.StringIO()) as stderr:
            code=cli.main(["--report",str(self.output),*args])
        return code,stdout.getvalue(),stderr.getvalue()

    def test_default_dry_run_and_readonly_engine_and_report(self):
        code,stdout,_=self.invoke()
        self.assertEqual(code,0)
        self.assertFalse(self.mocks[4].call_args.kwargs["execute"])
        self.assertIn("default_transaction_read_only=on",self.mocks[3].call_args.kwargs["connect_args"]["options"])
        self.assertEqual(json.loads(self.output.read_text())["transaction_outcome"],"read_only_rolled_back")
        self.assertNotIn("fake",stdout)
        self.mocks[3].return_value.dispose.assert_called_once()

    def test_execute_requires_additional_confirmation_before_engine_or_report(self):
        for args in (("--execute",),("--execute","--approve","wrong")):
            code,_,_=self.invoke(*args)
            self.assertEqual(code,1)
            self.mocks[3].assert_not_called()
            self.mocks[4].assert_not_called()
            self.assertFalse(self.output.exists())

    def test_explicit_approval_only_dispatches_to_mocked_executor(self):
        code,_,_=self.invoke("--execute","--approve",cli.APPROVAL_PHRASE)
        self.assertEqual(code,0)
        self.assertTrue(self.mocks[4].call_args.kwargs["execute"])
        self.assertEqual(self.mocks[4].call_args.kwargs["approval"],cli.APPROVAL_PHRASE)

    def test_existing_report_never_overwritten_or_database_opened(self):
        self.output.write_text("preserved")
        self.assertEqual(self.invoke()[0],1)
        self.assertEqual(self.output.read_text(),"preserved")
        self.mocks[3].assert_not_called()

    def test_file_authentication_failure_never_opens_database(self):
        self.mocks[2].side_effect=ValueError("manifest hash conflict")
        self.assertEqual(self.invoke()[0],1)
        self.mocks[3].assert_not_called()
        self.assertFalse(self.output.exists())

    def test_refresh_configuration_guard(self):
        cli.settings.LIVE_REFRESH_ENABLED=True
        self.assertEqual(self.invoke()[0],1)
        self.mocks[3].assert_not_called()

    def test_unknown_scope_or_target_arguments_have_no_execution_path(self):
        for args in (("--manifest","other.json"),("--event-id","other"),("--database-url","postgresql://other")):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                cli.main(["--report",str(self.output),*args])
        self.mocks[3].assert_not_called()

    def test_report_started_is_reserved_before_database_work(self):
        def create(*args,**kwargs):
            state=json.loads(self.output.read_text())
            self.assertEqual(state["status"],"started")
            self.assertEqual(state["transaction_outcome"],"not_yet_reported")
            return self.mocks[3].return_value
        self.mocks[3].side_effect=create
        self.assertEqual(self.invoke()[0],0)

    def test_postcommit_report_failure_prints_honest_commit_state(self):
        self.mocks[4].return_value.update(transaction_outcome="committed",
            committed={"events_created":1,"links_created":10},event_id="reviewed-event")
        with patch.object(cli,"atomic_json",side_effect=OSError("sensitive details")):
            code,_,stderr=self.invoke()
        self.assertEqual(code,1)
        self.assertIn('"transaction_outcome": "committed"',stderr)
        self.assertIn('"links_created": 10',stderr)
        self.assertNotIn("sensitive details",stderr)
        self.assertEqual(json.loads(self.output.read_text())["status"],"started")
