"""Pure fixtures and connection mocks; no application database/provider access."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.event_backfill import classify_events, read_prop_identities, retained_event
from scripts import classify_event_backfill as cli


START = datetime(2026, 10, 20, 19, tzinfo=timezone.utc)


def row(**changes):
    return {"prop_id": "prop-1", "odds_sport_key": "basketball_nba", "odds_event_id": "event-1",
            "game_time": START, "sport": "NBA", "team": "Home", "team_abbr": "HOM",
            "opponent": "Away", "is_home": True, **changes}


def report(**changes):
    return {"mode": "controlled_smoke", "status": "partial", "finished_at": START.isoformat(),
            "scope": {"event_id": "event-1", "sport_key": "basketball_nba"},
            "sport_result": {"source": "odds_api_props", "events_successfully_processed": 1,
                             "sport_key": "basketball_nba"},
            "event": {"id": "event-1", "sport_key": "basketball_nba", "home_team": "Home",
                      "away_team": "Away", "commence_time": START.isoformat()}, **changes}


class EventClassificationTests(unittest.TestCase):
    def classify(self, rows, evidence=(), **kwargs):
        return classify_events(rows, [retained_event(item) for item in evidence], **kwargs)

    def test_verified_metadata_not_player_team_inference(self):
        result = self.classify([row(team="UNK")], [report()])
        self.assertEqual(result["categories"]["verified_retained_metadata"]["prop_rows"], 1)
        self.assertEqual(result["samples"][0]["verified_event"]["home_team"], "Home")

    def test_consistent_derived_keys_without_evidence_are_unresolved(self):
        result = self.classify([row(), row(prop_id="prop-2")])
        self.assertEqual(result["categories"]["candidate_requires_verification"],
                         {"event_groups": 1, "prop_rows": 2})

    def test_inconsistent_derived_keys_are_diagnostics_not_authority(self):
        result = self.classify([row(), row(prop_id="prop-2", team="Traded")], [report()])
        self.assertEqual(result["diagnostic_group_counts"]["inconsistent_player_derived_game_keys"], 1)
        self.assertEqual(result["categories"]["verified_retained_metadata"]["event_groups"], 1)

    def test_unresolved_inconsistent_derived_keys_need_conflict_review(self):
        result = self.classify([row(), row(prop_id="prop-2", team="Traded")])
        self.assertEqual(result["categories"]["conflicting_metadata"]["prop_rows"], 2)
        self.assertNotIn("verified_event", result["samples"][0])

    def test_conflicting_stored_times(self):
        result = self.classify([row(), row(prop_id="prop-2", game_time=START.replace(hour=20))])
        self.assertEqual(result["categories"]["conflicting_metadata"]["prop_rows"], 2)

    def test_retained_schedule_difference_is_unresolved_conflict(self):
        result = self.classify([row(game_time=START.replace(hour=20))], [report()])
        self.assertIn("stored_time_differs_from_retained_metadata", result["samples"][0]["reasons"])
        self.assertEqual(result["categories"]["conflicting_metadata"]["event_groups"], 1)

    def test_retained_participant_conflict(self):
        second = report()
        second["event"]["home_team"] = "Other"
        result = self.classify([row()], [report(), second])
        self.assertEqual(result["categories"]["conflicting_metadata"]["event_groups"], 1)

    def test_missing_identity_does_not_merge_props(self):
        result = self.classify([row(odds_event_id=None), row(prop_id="prop-2", odds_event_id=None)])
        self.assertEqual(result["categories"]["missing_provider_identity"],
                         {"event_groups": 2, "prop_rows": 2})

    def test_synthetic_origin_is_preserved_and_not_verified(self):
        result = self.classify([row(odds_event_id="demo-1")])
        self.assertEqual(result["categories"]["legacy_unknown_origin"]["prop_rows"], 1)

    def test_bounded_deterministic_samples(self):
        result = self.classify([row(odds_event_id=str(index)) for index in range(5)], sample_limit=2)
        self.assertEqual(len(result["samples"]), 2)
        self.assertEqual(result["samples_truncated"], 3)
        self.assertEqual(sum(value["prop_rows"] for value in result["categories"].values()), 5)

    def test_naive_database_time_means_utc(self):
        result = self.classify([row(game_time=START.replace(tzinfo=None))], [report()])
        self.assertEqual(result["categories"]["verified_retained_metadata"]["prop_rows"], 1)

    def test_metadata_provenance_validation(self):
        self.assertIsNotNone(retained_event(report(status="completed")))
        self.assertIsNone(retained_event(report(mode="ordinary")))
        self.assertIsNone(retained_event(report(status="failed")))
        self.assertIsNone(retained_event(report(event={"id": "wrong"})))
        self.assertIsNone(retained_event({"event": report()["event"]}))
        malformed = report()
        malformed["sport_result"]["events_successfully_processed"] = "one"
        self.assertIsNone(retained_event(malformed))
        malformed = report()
        malformed["event"]["sport_key"] = []
        self.assertIsNone(retained_event(malformed))
        self.assertEqual(set(retained_event(report(secret="do-not-copy"))), {
            "provider", "provider_event_id", "sport_key", "home_team", "away_team", "scheduled_start_at"})

    def test_sports_namespace_is_part_of_identity(self):
        result = self.classify([row(), row(prop_id="prop-2", sport="WNBA", odds_sport_key="basketball_wnba")])
        self.assertEqual(result["total_event_groups"], 2)

    def test_samples_represent_categories_before_repeating_one_category(self):
        rows = [row(prop_id=str(index), odds_event_id=None) for index in range(100)]
        result = self.classify(rows + [row()], [report()], sample_limit=2)
        self.assertEqual({sample["category"] for sample in result["samples"]},
                         {"verified_retained_metadata", "missing_provider_identity"})
        self.assertEqual(result["samples_truncated"], 99)


class ReadOnlyConnectionTests(unittest.TestCase):
    def engine(self):
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        connection = engine.connect.return_value.__enter__.return_value
        connection.execute.return_value.mappings.return_value.all.return_value = [row()]
        return engine, connection

    def test_server_read_only_before_select_and_rollback(self):
        engine, connection = self.engine()
        self.assertEqual(len(read_prop_identities(engine)), 1)
        sql = [str(call.args[0]).strip() for call in connection.execute.call_args_list]
        self.assertEqual(sql[0], "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        self.assertIn("statement_timeout", sql[1])
        self.assertTrue(sql[2].startswith("SELECT"))
        connection.begin.return_value.rollback.assert_called_once()
        connection.commit.assert_not_called()

    def test_failure_rolls_back_without_commit(self):
        engine, connection = self.engine()
        connection.execute.side_effect = RuntimeError("query failed")
        with self.assertRaises(RuntimeError):
            read_prop_identities(engine)
        connection.begin.return_value.rollback.assert_called_once()
        connection.commit.assert_not_called()

    def test_refuses_oversized_inventory_and_non_postgres(self):
        engine, connection = self.engine()
        connection.execute.return_value.mappings.return_value.all.return_value = [row(), row()]
        with self.assertRaises(ValueError):
            read_prop_identities(engine, max_rows=1)
        connection.begin.return_value.rollback.assert_called_once()
        engine.dialect.name = "sqlite"
        with self.assertRaises(ValueError):
            read_prop_identities(engine)

    def test_cli_sanitizes_driver_errors(self):
        with patch.object(cli, "create_engine", side_effect=RuntimeError("secret database URL")), redirect_stderr(io.StringIO()) as error:
            self.assertEqual(cli.main(["--sample-limit", "0"]), 1)
        self.assertNotIn("secret", error.getvalue())

    def test_cli_loads_allowlisted_metadata_and_stdout_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report(secret="not-copied")), encoding="utf-8")
            with patch.object(cli, "create_engine") as factory, patch.object(cli, "read_prop_identities", return_value=[row()]), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["--retained-report", str(path)]), 0)
            result = json.loads(output.getvalue())
            self.assertTrue(result["read_only"])
            self.assertEqual(result["metadata_reports"]["accepted"], 1)
            self.assertNotIn("not-copied", output.getvalue())
            factory.return_value.dispose.assert_called_once()


if __name__ == "__main__":
    unittest.main()
