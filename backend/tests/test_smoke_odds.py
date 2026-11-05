"""Smoke wrapper regressions: mocked HTTP, sessions, lock; no live data access."""
import io
import json
import os
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from scripts import smoke_odds as smoke

SPORT = "basketball_nba"
EVENT_ID = "a" * 32
MARKET = "player_points"


def event():
    return {"id": EVENT_ID, "sport_key": SPORT, "home_team": "Home", "away_team": "Away",
            "commence_time": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()}


def response(data, cost=1, remaining=99, status=200):
    headers = {"x-requests-last": str(cost)}
    if remaining is not None:
        headers["x-requests-remaining"] = str(remaining)
    return SimpleNamespace(status_code=status, headers=headers, json=lambda: data)


class SmokeOddsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        configured = SimpleNamespace(DATABASE_URL="postgresql://fake:fake@localhost:5432/proppulse",
            ENVIRONMENT="development", LIVE_REFRESH_ENABLED=False, ODDS_MIN_REMAINING_CREDITS=50,
            ODDS_MAX_REQUESTS_PER_RUN=100, ODDS_MAX_CREDITS_PER_RUN=500)
        for target, name, value in ((smoke, "settings", configured),
                                     (smoke.ingestion, "API_KEY", "mock-secret-never-display"),
                                     (smoke.ingestion, "STATUS_DIR", self.temp.name)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = MagicMock()
        client_factory = patch.object(smoke.httpx, "Client")
        self.factory = client_factory.start()
        self.addCleanup(client_factory.stop)
        self.factory.return_value.__enter__.return_value = self.client
        self.db = MagicMock()
        self.db.execute.return_value.scalars.return_value.all.return_value = ["20261014_02"]
        sessions = patch.object(smoke.ingestion, "SessionLocal")
        self.sessions = sessions.start()
        self.addCleanup(sessions.stop)
        self.sessions.return_value.__enter__.return_value = self.db
        lock = patch.object(smoke, "odds_ingestion_lock", return_value=nullcontext(True))
        self.lock = lock.start()
        self.addCleanup(lock.stop)
        apply = patch.object(smoke.ingestion, "apply_updates_for_sport",
                             return_value={"sportsbook_offers_saved": 1, "sportsbook_snapshots_saved": 1})
        self.apply = apply.start()
        self.addCleanup(apply.stop)
        self.plan = smoke.validate_plan(SPORT, EVENT_ID, MARKET)
        self.run = {"run_id": str(uuid4()), "mode": "controlled_smoke", "status": "started",
                    "scope": self.plan, "metered_http_attempts": 0, "non_metered_http_attempts": 0,
                    "reported_credits_used": 0, "all_cost_headers_present": True, "provider_responses": []}
        self.event = event()
        self.market_data = {**self.event, "bookmakers": [{"key": "fanduel", "markets": [{"key": MARKET}]}]}
        self.odds_data = {**self.event, "bookmakers": [{"key": "fanduel", "title": "FanDuel",
            "markets": [{"key": MARKET, "last_update": datetime.now(timezone.utc).isoformat(), "outcomes": [
                {"name": "Over", "description": "Test Player", "point": 20.5, "price": -110},
                {"name": "Under", "description": "Test Player", "point": 20.5, "price": -105}]}]}]}

    def successful_responses(self):
        return [response([self.event], cost=0, remaining=100),
                response(self.market_data, remaining=99), response(self.odds_data, remaining=98)]

    def execute(self, responses=None):
        self.client.get.side_effect = self.successful_responses() if responses is None else responses
        return smoke.execute(self.plan, self.run)

    def test_dry_validation_never_opens_http_database_or_lock(self):
        with redirect_stdout(io.StringIO()) as output:
            code = smoke.main(["--sport", SPORT, "--event-id", EVENT_ID, "--market", MARKET])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "dry_validation")
        self.factory.assert_not_called()
        self.sessions.assert_not_called()
        self.lock.assert_not_called()
        self.assertNotIn("mock-secret", output.getvalue())
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_single_event_workflow_reports_two_paid_and_one_free_attempt(self):
        run = self.execute()
        self.assertEqual(run["status"], "completed")
        self.assertEqual((run["metered_http_attempts"], run["non_metered_http_attempts"]), (2, 1))
        self.assertEqual((run["credits_accounted"], run["reported_credits_used"], run["quota_remaining"]), (2, 2, 98))
        self.assertEqual(run["provider_requests_consumed"], 3)
        self.assertEqual(run["parsed_offers"], 1)
        self.assertEqual(self.apply.call_args.kwargs["scope"], {"event_id": EVENT_ID, "prop_type": "points"})
        self.db.commit.assert_called_once()
        self.db.rollback.assert_not_called()
        self.assertEqual(self.client.get.call_args_list[-1].kwargs["params"]["markets"], MARKET)
        path = os.path.join(self.temp.name, "odds_runs", run["run_id"] + ".json")
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["run_id"], run["run_id"])
        self.assertNotIn("mock-secret", json.dumps(report))
        self.assertFalse(os.path.exists(os.path.join(self.temp.name, "odds_ingestion_status.json")))

    def test_unavailable_market_stops_without_odds_or_persistence(self):
        self.market_data["bookmakers"] = []
        run = self.execute()
        self.assertEqual(run["status"], "market_unavailable")
        self.assertEqual(self.client.get.call_count, 2)
        self.assertEqual(run["metered_http_attempts"], 1)
        self.apply.assert_not_called()
        self.db.commit.assert_not_called()

    def matching_attempt(self, db, sport, rows, status, **kwargs):
        diagnostics = {"transaction_outcome": "pending", "row_counts": {"matched": len(rows)}}
        status["matching_diagnostics"] = diagnostics
        status["event_relationships"]["attempted"]["events_created"] = 1
        status["event_relationships"]["attempted"]["props_newly_linked"] = 1
        return {"sportsbook_offers_saved": len(rows), "matching_diagnostics": diagnostics}

    def test_matching_diagnostics_share_committed_state_in_all_report_locations(self):
        self.apply.side_effect = self.matching_attempt
        run = self.execute()
        self.assertEqual(run["matching_diagnostics"]["transaction_outcome"], "committed")
        self.assertEqual(run["committed_counts"]["matching_diagnostics"]["transaction_outcome"], "committed")
        self.assertEqual(run["event_relationships"]["committed"]["events_created"], 1)
        self.assertEqual(run["event_relationships"]["committed"]["props_newly_linked"], 1)

    def test_commit_failure_retains_attempted_matching_and_rollback_marker(self):
        self.apply.side_effect = self.matching_attempt
        self.db.commit.side_effect = RuntimeError("commit_failed")
        run = self.execute()
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["matching_diagnostics"]["transaction_outcome"], "rolled_back")
        self.assertEqual(run["matching_diagnostics"]["row_counts"], {"matched": 1})
        self.assertNotIn("committed_counts", run)
        self.assertEqual(run["event_relationships"]["committed"]["events_created"], 0)
        self.assertEqual(run["event_relationships"]["rolled_back"]["events_created"], 1)
        self.db.rollback.assert_called_once()

    def test_unknown_or_insufficient_quota_never_makes_paid_call(self):
        for remaining in (None, 51):
            with self.subTest(remaining=remaining):
                self.client.get.reset_mock()
                run = self.execute([response([self.event], cost=0, remaining=remaining)])
                self.assertEqual(run["error_category"], "provider_quota_unverified_or_insufficient")
                self.assertEqual(self.client.get.call_count, 1)
                self.apply.assert_not_called()

    def test_unexpected_market_scope_never_reaches_persistence(self):
        self.odds_data["bookmakers"][0]["markets"].append({"key": "player_rebounds"})
        run = self.execute()
        self.assertEqual(run["error_category"], "unexpected_market_scope_expansion")
        self.apply.assert_not_called()
        self.db.commit.assert_not_called()

    def test_changed_event_identity_never_reaches_persistence(self):
        self.odds_data["id"] = "different"
        run = self.execute()
        self.assertEqual(run["error_category"], "odds_response_scope_mismatch")
        self.apply.assert_not_called()

    def test_transient_metered_error_has_no_retry(self):
        run = self.execute([response([self.event], cost=0, remaining=100), response({}, status=503)])
        self.assertEqual(run["error_category"], "provider_http_503")
        self.assertEqual(self.client.get.call_count, 2)
        self.assertEqual(run["metered_http_attempts"], 1)
        self.apply.assert_not_called()

    def test_lock_contention_has_no_http_or_database_access(self):
        self.lock.return_value = nullcontext(False)
        run = self.execute([])
        self.assertEqual(run["status"], "skipped_locked")
        self.client.get.assert_not_called()
        self.sessions.assert_not_called()

    def test_failed_commit_rolls_back_without_committed_success_counters(self):
        self.db.commit.side_effect = ValueError("database parameters must not escape")
        run = self.execute()
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error_category"], "ValueError")
        self.assertNotIn("committed_counts", run)
        self.assertNotIn("sport_result", run)
        self.db.rollback.assert_called_once()

    def test_unexpected_cost_stops_before_additional_request(self):
        run = self.execute([response([self.event], cost=0, remaining=100),
                            response(self.market_data, cost=3)])
        self.assertEqual(run["error_category"], "unexpected_provider_cost")
        self.assertEqual(self.client.get.call_count, 2)
        self.apply.assert_not_called()

    def test_configuration_guards_reject_unsafe_targets(self):
        for field, value in (("LIVE_REFRESH_ENABLED", True), ("DATABASE_URL", "sqlite:///:memory:"),
                             ("DATABASE_URL", "postgresql://localhost:5432/other"),
                             ("ENVIRONMENT", "production")):
            with self.subTest(field=field, value=value), patch.object(smoke.settings, field, value):
                with self.assertRaises(ValueError):
                    smoke.validate_plan(SPORT, EVENT_ID, MARKET)
        self.factory.assert_not_called()
        self.sessions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
