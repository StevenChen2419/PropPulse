"""Synthetic response fixtures and MockTransport only; no live provider access."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from app.services import espn_contract_collection as collector


class CollectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name)
        self.out = self.parent / "new_collection"
        self.now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
        self.delays = []

    def plan(self, **changes):
        return collector.build_collection_plan(**{"start_date": "2026-10-15", "end_date": "2026-10-15",
            "endpoints": ["teams"], "team_ids": ["1"], "game_ids": ["402000001"],
            "request_budget": 1, "output_dir": str(self.out), **changes})

    def collect(self, handler, plan=None):
        plan = plan or self.plan()
        return collector.execute_collection(plan, authorization=collector.AUTHORIZATION_PHRASE,
            reviewed_plan_sha256=plan["plan_sha256"], transport=httpx.MockTransport(handler),
            sleep=self.delays.append, clock=lambda: self.now)

    def test_default_plan_no_client_no_directory(self):
        with patch.object(httpx, "Client") as client:
            plan = self.plan()
        client.assert_not_called()
        self.assertFalse(self.out.exists())
        self.assertEqual(plan["mode"], "dry_run")

    def test_only_fixed_https_nba_templates(self):
        plan = self.plan(endpoints=["summary", "scoreboard", "roster", "teams"], team_ids=["2", "1"],
                         game_ids=["402000001"], request_budget=5)
        self.assertEqual(len(plan["requests"]), 5)
        for request in plan["requests"]:
            self.assertTrue(request["url"].startswith(collector.BASE_URL + "/"))
        self.assertEqual(plan["requests"][-1]["contract_status"], "unverified_contract_audit")
        self.assertEqual(plan["requests"][0]["contract_status"], "repository_used")

    def test_plan_digest_reproducible_canonical_order(self):
        first = self.plan(team_ids=["2", "1"], endpoints=["roster", "teams"], request_budget=3)
        second = self.plan(team_ids=["1", "2"], endpoints=["teams", "roster"], request_budget=3)
        self.assertEqual(first, second)

    def test_scope_and_limits_rejected(self):
        cases = [{"start_date": "2026-10-16"}, {"end_date": "2026-11-01"}, {"start_date": "bad"},
            {"start_date": "20261015"}, {"team_ids": ["1", "2", "3"]}, {"game_ids": list(map(str, range(9)))},
            {"team_ids": ["1", "1"]}, {"team_ids": ["../secret"]}, {"game_ids": ["1?token=secret"]},
            {"endpoints": ["https://evil.invalid"]}, {"endpoints": []}, {"endpoints": ["teams", "teams"]},
            {"team_ids": []}, {"game_ids": []}, {"request_budget": 0}, {"request_budget": 33},
            {"request_budget": True}, {"max_retries": 3}, {"max_retries": -1}, {"min_delay_seconds": .9},
            {"min_delay_seconds": float("nan")}, {"redaction_policy": "none"}]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(collector.CollectionRejected):
                self.plan(**changes)
        self.assertFalse(self.out.exists())

    def test_fourteen_days_allowed_fifteen_rejected(self):
        self.assertEqual(len(self.plan(endpoints=["scoreboard"], end_date="2026-10-28", request_budget=14)["requests"]), 14)
        with self.assertRaises(collector.CollectionRejected):
            self.plan(endpoints=["scoreboard"], end_date="2026-10-29", request_budget=15)

    def test_base_requests_cannot_exceed_attempt_budget(self):
        with self.assertRaises(collector.CollectionRejected):
            self.plan(endpoints=["teams", "scoreboard"])

    def test_explicit_separate_authorization_before_client_or_write(self):
        plan = self.plan()
        with patch.object(httpx, "Client") as client, self.assertRaises(collector.CollectionRejected):
            collector.execute_collection(plan, authorization="yes", reviewed_plan_sha256=plan["plan_sha256"])
        client.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_reviewed_digest_required_before_client_or_write(self):
        with patch.object(httpx, "Client") as client, self.assertRaises(collector.CollectionRejected):
            collector.execute_collection(self.plan(), authorization=collector.AUTHORIZATION_PHRASE, reviewed_plan_sha256="wrong")
        client.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_mutated_url_even_rehashed_is_rejected(self):
        plan = self.plan()
        plan["requests"][0]["url"] = "https://evil.invalid/"
        plan["plan_sha256"] = collector._digest({key: value for key, value in plan.items() if key != "plan_sha256"})
        with patch.object(httpx, "Client") as client, self.assertRaises(collector.CollectionRejected):
            collector.execute_collection(plan, authorization=collector.AUTHORIZATION_PHRASE, reviewed_plan_sha256=plan["plan_sha256"])
        client.assert_not_called()

    def test_mutated_hidden_extra_field_is_rejected(self):
        plan = self.plan()
        plan["auth"] = "private"
        with self.assertRaises(collector.CollectionRejected):
            self.collect(lambda request: self.fail("No request allowed"), plan)

    def test_no_arbitrary_outdir_overwrite_or_relative_path(self):
        self.out.mkdir()
        with self.assertRaises(collector.CollectionRejected):
            self.plan()
        with self.assertRaises(collector.CollectionRejected):
            self.plan(output_dir="relative")

    def test_parent_must_exist_and_traversal_not_accepted(self):
        with self.assertRaises(collector.CollectionRejected):
            self.plan(output_dir=str(self.out / "child"))
        with self.assertRaises(collector.CollectionRejected):
            self.plan(output_dir=str(self.parent / ".." / "unexpected"))

    def test_reparse_or_symlink_ancestors_rejected(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=info), self.assertRaises(collector.CollectionRejected):
            self.plan()
        info = SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
        with patch.object(Path, "lstat", return_value=info), self.assertRaises(collector.CollectionRejected):
            self.plan()

    def test_success_manifest_redacted_artifact_hash(self):
        result = self.collect(lambda request: httpx.Response(200, json={"sports": [{"name": "NBA"}]}))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["request_attempts"], 1)
        self.assertFalse(result["raw_payloads_retained"])
        attempt = result["attempts"][0]
        artifact = self.out / attempt["artifact"]
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), attempt["sha256"])
        self.assertEqual(artifact.stat().st_size, attempt["bytes"])
        envelope = json.loads(artifact.read_bytes())
        self.assertEqual(envelope["collection_version"], 1)
        self.assertEqual(envelope["observed_at"], self.now.isoformat())
        self.assertEqual(envelope["payload"], {"sports": [{"name": "NBA"}]})

    def test_recursive_redaction_urls_credentials_private_pii_no_headers(self):
        secret = "PRIVATE_VALUE_SHOULD_NEVER_BE_RETAINED"
        payload = {"athlete": {"displayName": "Public Athlete", "id": "1", "dateOfBirth": secret,
                    "nested": [{"API-Key": secret, "headers": {"Authorization": secret}}]},
                   "link": f"https://user:{secret}@example.invalid/?token={secret}",
                   "note": "person@example.invalid", "other": f"Bearer {secret}", "password": secret,
                   "person@example.invalid": secret}
        self.collect(lambda request: httpx.Response(200, json=payload, headers={"Set-Cookie": f"private={secret}"}))
        all_files = "".join(path.read_text() for path in self.out.iterdir())
        self.assertNotIn(secret, all_files)
        self.assertNotIn("person@example.invalid", all_files)
        self.assertNotIn("Set-Cookie", all_files)
        self.assertIn("Public Athlete", all_files)
        self.assertIn("[REDACTED]", all_files)

    def test_server_cookie_not_sent_on_next_request_and_links_not_followed(self):
        calls = []
        def handler(request):
            calls.append(str(request.url))
            self.assertNotIn("cookie", request.headers)
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, json={"next": "https://evil.invalid/"}, headers={"Set-Cookie": "sensitive=secret; Path=/"})
        result = self.collect(handler, self.plan(endpoints=["teams", "scoreboard"], request_budget=2))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.delays, [1.0])

    def test_live_client_configuration_has_no_ambient_auth_redirects_or_proxy(self):
        original = httpx.Client
        with patch.object(httpx, "Client", wraps=original) as client:
            self.collect(lambda request: httpx.Response(200, json={}))
        options = client.call_args.kwargs
        self.assertFalse(options["trust_env"])
        self.assertFalse(options["follow_redirects"])
        self.assertIsNone(options["auth"])
        self.assertIsInstance(options["transport"], httpx.MockTransport)
        self.assertEqual(options["timeout"].read, collector.TIMEOUT_SECONDS)

    def test_retry_server_errors_delay_every_attempt_and_budget_counts(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(503 if len(calls) < 3 else 200, json={})
        result = self.collect(handler, self.plan(request_budget=3, max_retries=2))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["request_attempts"], 3)
        self.assertEqual(self.delays, [1.0, 1.0])

    def test_retry_budget_cannot_expand_to_other_requests(self):
        result = self.collect(lambda request: httpx.Response(503),
            self.plan(endpoints=["teams", "scoreboard"], request_budget=2, max_retries=2))
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(result["request_attempts"], 2)
        self.assertEqual(self.delays, [1.0])

    def test_connect_and_read_timeout_retry_only_within_budget(self):
        for error in (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError):
            with self.subTest(error=error):
                self.out = self.parent / error.__name__
                calls = []
                def handler(request):
                    calls.append(request)
                    if len(calls) == 1:
                        raise error("Sensitive error detail must not be echoed")
                    return httpx.Response(200, json={})
                result = self.collect(handler, self.plan(request_budget=2, max_retries=1))
                self.assertEqual((result["status"], result["request_attempts"]), ("completed", 2))

    def test_other_transport_errors_not_retried(self):
        def handler(request):
            raise httpx.RemoteProtocolError("Partial message with private content")
        result = self.collect(handler, self.plan(request_budget=3, max_retries=2))
        self.assertEqual(result["request_attempts"], 1)
        self.assertEqual(result["status"], "stopped")

    def test_redirect_429_and_4xx_stop_without_follow_or_retry(self):
        for status in (301, 302, 401, 403, 404, 429):
            with self.subTest(status=status):
                self.out = self.parent / str(status)
                result = self.collect(lambda request: httpx.Response(status, headers={"Location": "https://evil.invalid"}),
                                      self.plan(request_budget=3, max_retries=2))
                self.assertEqual(result["request_attempts"], 1)
                self.assertEqual(result["status"], "stopped")

    def test_invalid_partial_duplicate_nonfinite_json_stops(self):
        for index, raw in enumerate((b'{"unfinished":', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'\xff', b'html')):
            with self.subTest(raw=raw):
                self.out = self.parent / str(index)
                result = self.collect(lambda request: httpx.Response(200, content=raw), self.plan(request_budget=3, max_retries=2))
                self.assertEqual(result["request_attempts"], 1)
                self.assertEqual(result["attempts"][0]["status"], "invalid_or_partial_json")
                self.assertEqual([path.name for path in self.out.iterdir()], ["manifest.json"])

    def test_response_byte_bound_stops_without_raw_artifact(self):
        raw = b'{"x":"' + b'a' * collector.MAX_RESPONSE_BYTES + b'"}'
        result = self.collect(lambda request: httpx.Response(200, content=raw))
        self.assertEqual(result["status"], "stopped")
        self.assertEqual([path.name for path in self.out.iterdir()], ["manifest.json"])

    def test_compressed_response_rejected_before_stream_read_or_decompression(self):
        for encoding in ("gzip", "br", "deflate"):
            with self.subTest(encoding=encoding):
                self.out = self.parent / encoding
                reads = []
                class TrapStream(httpx.SyncByteStream):
                    def __iter__(self):
                        reads.append(True)
                        raise AssertionError("Compressed body must not be read or decompressed")
                def handler(request):
                    self.assertEqual(request.headers["Accept-Encoding"], "identity")
                    return httpx.Response(200, headers={"Content-Encoding": encoding}, stream=TrapStream())
                result = self.collect(handler, self.plan(request_budget=3, max_retries=2))
                self.assertEqual(result["status"], "stopped")
                self.assertEqual(result["request_attempts"], 1)
                self.assertEqual(reads, [])
                self.assertEqual([path.name for path in self.out.iterdir()], ["manifest.json"])

    def test_elapsed_stream_deadline_stops_without_retry_or_artifact(self):
        plan = self.plan(request_budget=3, max_retries=2)
        times = iter([0, 1, collector.TIMEOUT_SECONDS + 1])
        result = collector.execute_collection(plan, authorization=collector.AUTHORIZATION_PHRASE,
            reviewed_plan_sha256=plan["plan_sha256"], transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
            sleep=self.delays.append, clock=lambda: self.now, monotonic=lambda: next(times))
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["request_attempts"], 1)
        self.assertEqual([path.name for path in self.out.iterdir()], ["manifest.json"])

    def test_deadline_is_rechecked_after_stream_eof(self):
        times = iter([0, 1, 2, collector.TIMEOUT_SECONDS + 1])
        class LateEofStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b"{}"
        plan = self.plan(request_budget=3, max_retries=2)
        result = collector.execute_collection(plan, authorization=collector.AUTHORIZATION_PHRASE,
            reviewed_plan_sha256=plan["plan_sha256"], transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=LateEofStream())),
            clock=lambda: self.now, monotonic=lambda: next(times))
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["request_attempts"], 1)
        self.assertEqual([path.name for path in self.out.iterdir()], ["manifest.json"])

    def test_interruptions_preserve_sanitized_attempt_audit_without_retry(self):
        for failure in (KeyboardInterrupt, SystemExit, RuntimeError):
            with self.subTest(failure=failure.__name__):
                self.out = self.parent / failure.__name__
                calls = []
                def handler(request):
                    calls.append(request)
                    if len(calls) == 2:
                        raise failure("PRIVATE_INTERRUPT_DETAIL")
                    return httpx.Response(200, json={})
                with self.assertRaises(failure):
                    self.collect(handler, self.plan(endpoints=["teams", "scoreboard"], request_budget=3, max_retries=1))
                text = (self.out / "manifest.json").read_text()
                manifest = json.loads(text)
                expected = "failed" if failure is RuntimeError else "interrupted"
                self.assertEqual(manifest["status"], expected)
                self.assertEqual(manifest["request_attempts"], 2)
                self.assertEqual([item["status"] for item in manifest["attempts"]], ["collected", expected])
                self.assertEqual(len(calls), 2)
                self.assertNotIn("PRIVATE_INTERRUPT_DETAIL", text)
                self.assertTrue((self.out / "response_001.json").exists())
                self.assertFalse((self.out / "response_002.json").exists())

    def test_sleep_interruption_does_not_count_an_unissued_request(self):
        calls = []
        plan = self.plan(endpoints=["teams", "scoreboard"], request_budget=2)
        with self.assertRaises(KeyboardInterrupt):
            collector.execute_collection(plan, authorization=collector.AUTHORIZATION_PHRASE,
                reviewed_plan_sha256=plan["plan_sha256"], transport=httpx.MockTransport(lambda request: (calls.append(request) or httpx.Response(200, json={}))),
                sleep=lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()), clock=lambda: self.now)
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual((manifest["status"], manifest["request_attempts"], len(calls)), ("interrupted", 1, 1))
        self.assertEqual(manifest["attempts"][0]["status"], "collected")

    def test_partial_files_created_by_failed_writes_are_removed(self):
        original = collector.os.fdopen
        for failure in (KeyboardInterrupt, OSError):
            with self.subTest(failure=failure.__name__):
                self.out = self.parent / failure.__name__
                self.out.mkdir()
                def broken_open(descriptor, mode):
                    file = original(descriptor, mode)
                    class PartialWriter:
                        def __enter__(self):
                            return self
                        def __exit__(self, *args):
                            file.close()
                        def close(self):
                            file.close()
                        def write(self, raw):
                            file.write(raw[:12])
                            file.flush()
                            raise failure("PRIVATE_WRITE_DETAIL")
                    return PartialWriter()
                with patch.object(collector.os, "fdopen", side_effect=broken_open), self.assertRaises(failure):
                    collector._exclusive_json(self.out, "response_001.json", {"payload": "redacted"})
                self.assertEqual(list(self.out.iterdir()), [])

    def test_fdopen_failure_closes_descriptor_and_removes_new_file(self):
        self.out.mkdir()
        descriptors = []
        def fail_open(descriptor, mode):
            descriptors.append(descriptor)
            raise OSError("PRIVATE_OPEN_DETAIL")
        with patch.object(collector.os, "fdopen", side_effect=fail_open), self.assertRaises(OSError):
            collector._exclusive_json(self.out, "response_001.json", {})
        with self.assertRaises(OSError):
            collector.os.fstat(descriptors[0])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_audit_write_failure_does_not_mask_original_interruption(self):
        original = collector._exclusive_json
        def write(directory, name, value):
            if name == "manifest.json":
                raise OSError("PRIVATE_DISK_DETAIL")
            return original(directory, name, value)
        with patch.object(collector, "_exclusive_json", side_effect=write), self.assertRaises(KeyboardInterrupt):
            self.collect(lambda request: (_ for _ in ()).throw(KeyboardInterrupt("PRIVATE_INTERRUPT_DETAIL")))
        self.assertFalse((self.out / "manifest.json").exists())

    def test_response_shapes_are_opaque_not_normalized_or_promoted(self):
        result = self.collect(lambda request: httpx.Response(200, json={"unrecognized": [0, False, None]}))
        payload = json.loads((self.out / result["attempts"][0]["artifact"]).read_text())["payload"]
        self.assertEqual(payload, {"unrecognized": [0, False, None]})

    def test_existing_artifact_never_overwritten(self):
        def handler(request):
            (self.out / "response_001.json").write_text("existing")
            return httpx.Response(200, json={})
        result = self.collect(handler)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual((self.out / "response_001.json").read_text(), "existing")

    def test_existing_manifest_never_overwritten(self):
        def handler(request):
            (self.out / "manifest.json").write_text("existing")
            return httpx.Response(200, json={})
        with self.assertRaises(FileExistsError):
            self.collect(handler)
        self.assertEqual((self.out / "manifest.json").read_text(), "existing")

    def test_clock_requires_timezone(self):
        plan = self.plan()
        with self.assertRaises(collector.CollectionRejected):
            collector.execute_collection(plan, authorization=collector.AUTHORIZATION_PHRASE,
                reviewed_plan_sha256=plan["plan_sha256"], transport=httpx.MockTransport(lambda request: self.fail("No request")),
                clock=lambda: datetime(2026, 10, 17))
        self.assertFalse(self.out.exists())

    def test_collector_import_has_no_database_settings_models(self):
        source = "import sys; import app.services.espn_contract_collection; print(any(x in sys.modules for x in ('app.database','app.config','app.models')))"
        result = subprocess.run([sys.executable, "-c", source], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "False")

    def cli(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "collect_espn_contracts.py"
        spec = importlib.util.spec_from_file_location("collector_cli_fixture", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def cli_args(self):
        return ["--sport", "NBA", "--start-date", "2026-10-15", "--end-date", "2026-10-15",
                "--team-id", "1", "--game-id", "402000001", "--endpoint", "teams", "--request-budget", "1",
                "--min-delay-seconds", "1", "--max-retries", "0", "--redaction-policy", collector.REDACTION_POLICY,
                "--outdir", str(self.out)]

    def test_cli_default_prints_plan_without_client_or_files(self):
        output = io.StringIO()
        with patch.object(httpx, "Client") as client, redirect_stdout(output):
            result = self.cli().main(self.cli_args())
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "dry_run")
        client.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_cli_requires_explicit_ids_delay_retries_and_redaction_policy(self):
        for flag in ("--team-id", "--game-id", "--min-delay-seconds", "--max-retries", "--redaction-policy"):
            with self.subTest(flag=flag):
                arguments = self.cli_args()
                position = arguments.index(flag)
                del arguments[position:position + 2]
                with patch.object(httpx, "Client") as client, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    self.cli().main(arguments)
                self.assertEqual(error.exception.code, 2)
                client.assert_not_called()
                self.assertFalse(self.out.exists())

    def test_cli_execute_missing_separate_auth_rejected_without_client(self):
        output = io.StringIO()
        with patch.object(httpx, "Client") as client, redirect_stdout(output):
            result = self.cli().main(self.cli_args() + ["--execute"])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "rejected")
        client.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_cli_dryrun_rejects_execution_flags(self):
        with redirect_stdout(io.StringIO()):
            result = self.cli().main(self.cli_args() + ["--reviewed-plan-sha256", "notreviewed"])
        self.assertEqual(result, 1)

    def test_cli_cancellation_returns_nonzero_without_private_exception_text(self):
        output = io.StringIO()
        with patch.object(collector, "execute_collection", side_effect=KeyboardInterrupt("PRIVATE_INTERRUPT_DETAIL")), redirect_stdout(output):
            result = self.cli().main(self.cli_args() + ["--execute"])
        self.assertEqual(result, 130)
        self.assertEqual(json.loads(output.getvalue())["status"], "interrupted")
        self.assertNotIn("PRIVATE_INTERRUPT_DETAIL", output.getvalue())

    def test_cli_unexpected_failures_and_system_exit_are_sanitized(self):
        for failure in (SystemExit, RuntimeError, ValueError):
            output = io.StringIO()
            with self.subTest(failure=failure.__name__), patch.object(collector, "execute_collection", side_effect=failure("PRIVATE_FAILURE_DETAIL")), redirect_stdout(output):
                result = self.cli().main(self.cli_args() + ["--execute"])
            self.assertEqual(result, 1)
            self.assertIn(json.loads(output.getvalue())["status"], ("interrupted", "rejected"))
            self.assertNotIn("PRIVATE_FAILURE_DETAIL", output.getvalue())
