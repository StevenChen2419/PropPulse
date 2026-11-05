"""Pure fixtures: no application lifespan, provider requests or database access."""
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from app.services.event_link_manifest import build_event_link_manifest, revalidate_event_link_manifest
from scripts import prepare_event_links as cli


START = datetime(2026, 10, 20, 19, tzinfo=timezone.utc)
EVENT = str(UUID(int=100))
SOURCE = "protected-local/retained-controlled-smoke.json"


def row(index=1, **changes):
    return {"prop_id": str(UUID(int=index)), "player_id": str(UUID(int=index + 1000)),
            "player_name": "Verified Athlete", "event_id": None, "prop_type": "points", "line": 20.5,
            "odds_sport_key": "basketball_nba", "odds_event_id": "26b036ff107f3c658258eaf4a6f26228",
            "game_time": START, "sport": "NBA", "team": "Boston Celtics", "team_abbr": "BOS",
            "opponent": "Detroit Pistons", "is_home": False, **changes}


def report():
    return {"mode": "controlled_smoke", "status": "completed", "finished_at": START.isoformat(),
            "scope": {"event_id": row()["odds_event_id"], "sport_key": "basketball_nba"},
            "sport_result": {"source": "odds_api_props", "events_successfully_processed": 1,
                             "sport_key": "basketball_nba"},
            "event": {"id": row()["odds_event_id"], "sport_key": "basketball_nba",
                      "home_team": "Detroit Pistons", "away_team": "Boston Celtics",
                      "commence_time": START.isoformat()}}


def build(rows=None, evidence=None, **kwargs):
    return build_event_link_manifest(rows if rows is not None else [row()],
                                     report() if evidence is None else evidence,
                                     evidence_source=SOURCE, **kwargs)


class EventLinkManifestTests(unittest.TestCase):
    def test_ten_verified_candidates_include_exact_ids_and_provenance(self):
        result = build([row(index) for index in range(1, 11)])
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["execution_supported"])
        self.assertEqual({item["prop_id"] for item in result["candidates"]},
                         {row(index)["prop_id"] for index in range(1, 11)})
        self.assertEqual(result["event"]["home_team"], "Detroit Pistons")
        expected_hash = hashlib.sha256(json.dumps(report(), sort_keys=True, separators=(",", ":"),
                                                   ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(result["evidence"]["sha256"], expected_hash)
        self.assertIn("player_identity_sha256", result["candidates"][0]["expected"])

    def test_unknown_mutable_player_team_cannot_replace_provider_participants(self):
        result = build([row(team="UNK")])
        self.assertEqual(result["event"]["away_team"], "Boston Celtics")
        self.assertEqual(len(result["candidates"]), 1)

    def test_opponent_and_home_side_must_match_authoritative_participants(self):
        for changes in ({"opponent": "Boston Celtics"}, {"is_home": True},
                        {"opponent": "Other Team"}, {"opponent": "DET"}):
            with self.subTest(changes=changes):
                result = build([row(**changes)])
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["rejected"][0]["reason"], "stored_participant_side_conflict")

    def test_unknown_missing_opponent_or_home_side_never_qualifies(self):
        for opponent in (None, "", "UNK", "TBD", "unknown"):
            with self.subTest(opponent=opponent):
                result = build([row(opponent=opponent)])
                self.assertFalse(result["candidates"])
                self.assertEqual(result["rejected"][0]["reason"], "missing_or_unknown_stored_opponent")
        for field in ("opponent", "is_home"):
            value = row()
            value.pop(field)
            with self.subTest(missing=field):
                self.assertFalse(build([value])["candidates"])
        for value in (None, "false", 0):
            with self.subTest(is_home=value):
                self.assertFalse(build([row(is_home=value)])["candidates"])

    def test_home_player_and_away_player_both_qualify_from_stored_side_evidence(self):
        result = build([row(team="Unrelated mutable team"),
                        row(2, team="UNK", opponent="Boston Celtics", is_home=True)])
        self.assertEqual(len(result["candidates"]), 2)

    def test_conflicting_stored_side_rejects_only_affected_candidate(self):
        result = build([row(), row(2, is_home=True)])
        self.assertEqual([item["prop_id"] for item in result["candidates"]], [row()["prop_id"]])
        self.assertEqual([item["prop_id"] for item in result["rejected"]], [row(2)["prop_id"]])

    def test_schedule_conflict_blocks_entire_group_without_rounding(self):
        result = build([row(), row(2, game_time=START.replace(second=3))])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(len(result["rejected"]), 2)
        self.assertEqual(result["rejected"][0]["reason"], "unverified_or_conflicting_event_group")

    def test_missing_provider_identity_and_other_events_remain_unresolved(self):
        result = build([row(), row(2, odds_event_id=None), row(3, odds_event_id="unverified")])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["unresolved_inventory_rows"], 2)

    def test_already_linked_requires_explicit_same_target(self):
        self.assertEqual(build([row(event_id=EVENT)])["rejected"][0]["reason"], "known_event_link_conflict")
        result = build([row(event_id=EVENT)], target_event_id=EVENT)
        self.assertEqual(result["candidates"][0]["relationship"], "reused")

    def test_other_known_event_relationship_rejected(self):
        result = build([row(event_id=str(UUID(int=101)))], target_event_id=EVENT)
        self.assertFalse(result["candidates"])

    def test_stale_values_rejected_for_each_identity_field(self):
        manifest = build(target_event_id=EVENT)
        changes = {"player_name": "Changed", "player_id": str(UUID(int=2000)),
                   "opponent": "Changed", "is_home": True, "team": "Changed",
                   "line": 21.5, "prop_type": "rebounds", "event_id": str(UUID(int=200))}
        for key, value in changes.items():
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "stale_manifest_records"):
                revalidate_event_link_manifest(manifest, [row(**{key: value})], report(),
                                               evidence_source=SOURCE, target_event_id=EVENT)

    def test_fresh_repeat_and_same_target_link_idempotent(self):
        manifest = build(target_event_id=EVENT)
        repeated = revalidate_event_link_manifest(manifest, [row()], report(), evidence_source=SOURCE,
                                                   target_event_id=EVENT)
        self.assertEqual(repeated, manifest)
        linked = revalidate_event_link_manifest(manifest, [row(event_id=EVENT)], report(),
                                                evidence_source=SOURCE, target_event_id=EVENT)
        self.assertEqual(linked["candidates"][0]["relationship"], "reused")

    def test_added_or_deleted_scope_record_invalidates_manifest(self):
        for rows in ([], [row(), row(2)]):
            with self.subTest(rows=len(rows)), self.assertRaisesRegex(ValueError, "stale_manifest_records"):
                revalidate_event_link_manifest(build(), rows, report(), evidence_source=SOURCE)

    def test_unrelated_record_change_does_not_stale_or_modify_rows(self):
        original = [row(), row(2, odds_event_id="other")]
        saved = deepcopy(original)
        manifest = build(original)
        fresh = [row(), row(2, odds_event_id="other", opponent="Changed")]
        revalidate_event_link_manifest(manifest, fresh, report(), evidence_source=SOURCE)
        self.assertEqual(original, saved)

    def test_changed_evidence_or_source_rejected(self):
        evidence = report()
        evidence["finished_at"] = START.replace(hour=20).isoformat()
        with self.assertRaisesRegex(ValueError, "stale_manifest_evidence"):
            revalidate_event_link_manifest(build(), [row()], evidence, evidence_source=SOURCE)
        with self.assertRaisesRegex(ValueError, "stale_manifest_evidence"):
            revalidate_event_link_manifest(build(), [row()], report(), evidence_source="different")

    def test_manifest_edit_detected(self):
        manifest = build()
        manifest["candidates"][0]["expected"]["line"] = 999
        with self.assertRaisesRegex(ValueError, "manifest_integrity_conflict"):
            revalidate_event_link_manifest(manifest, [row()], report(), evidence_source=SOURCE)

    def test_invalid_retained_report_or_unknown_participants_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_retained_report"):
            build(evidence={})
        for team in ("UNK", "unknown", "TBD", "Boston Celtics"):
            evidence = report()
            evidence["event"]["home_team"] = team
            with self.subTest(team=team), self.assertRaisesRegex(ValueError, "invalid_retained"):
                build(evidence=evidence)

    def test_incomplete_inventory_is_not_eligible(self):
        for key in ("event_id", "player_name", "player_id", "prop_type", "line"):
            value = row()
            value.pop(key)
            with self.subTest(key=key):
                self.assertEqual(build([value])["candidates"], [])

    def test_duplicate_uuid_and_scope_bound_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate_inventory_prop"):
            build([row(), row()])
        with self.assertRaisesRegex(ValueError, "candidate_bound_exceeded"):
            build([row(index) for index in range(1, 12)])

    def test_manifest_json_contains_only_safe_allowlisted_report_values(self):
        evidence = report()
        evidence["api_key"] = "never-copy-this"
        text = json.dumps(build(evidence=evidence))
        self.assertNotIn("never-copy-this", text)
        self.assertNotIn("api_key", text)


class EventLinkManifestCliTests(unittest.TestCase):
    def test_explicit_arguments_and_no_execution_option(self):
        for args in ([], ["--execute"], ["--retained-report", "report.json"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.main(args)

    def test_mocked_read_only_inventory_saved_without_raw_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.json", root / "protected" / "manifest.json"
            source.write_text(json.dumps(report()), encoding="utf-8")
            with patch.object(cli, "MANIFEST_DIRECTORY", root / "protected"), \
                    patch.object(cli, "create_engine") as engine, \
                    patch.object(cli, "read_prop_identities", return_value=[row()]) as reader, \
                    redirect_stdout(io.StringIO()) as stdout:
                result = cli.main(["--retained-report", str(source), "--output", str(output)])
            self.assertEqual(result, 0)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["candidates"]), 1)
            self.assertTrue(manifest["dry_run"])
            self.assertFalse(manifest["execution_supported"])
            reader.assert_called_once_with(engine.return_value)
            engine.return_value.dispose.assert_called_once()
            self.assertNotIn(row()["prop_id"], stdout.getvalue())

    def test_output_scope_and_existing_files_rejected_before_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protected = root / "protected"
            protected.mkdir()
            existing = protected / "existing.json"
            existing.write_text("preserved", encoding="utf-8")
            for output in (root / "outside.json", existing, protected / "not-json.txt"):
                with self.subTest(output=output.name), patch.object(cli, "MANIFEST_DIRECTORY", protected), \
                        patch.object(cli, "create_engine") as factory, redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(["--retained-report", "unused.json", "--output", str(output)]), 1)
                    factory.assert_not_called()
            self.assertEqual(existing.read_text(encoding="utf-8"), "preserved")

    def test_invalid_report_and_oversized_report_fail_before_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            for content in ("{}", " " * 1000001):
                source.write_text(content, encoding="utf-8")
                with patch.object(cli, "MANIFEST_DIRECTORY", root / "protected"), \
                        patch.object(cli, "create_engine") as factory, redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(["--retained-report", str(source), "--output",
                                               str(root / "protected" / "new.json")]), 1)
                    factory.assert_not_called()

    def test_database_errors_sanitized_without_manifest_or_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.json", root / "protected" / "new.json"
            source.write_text(json.dumps(report()), encoding="utf-8")
            with patch.object(cli, "MANIFEST_DIRECTORY", root / "protected"), \
                    patch.object(cli, "create_engine") as engine, \
                    patch.object(cli, "read_prop_identities", side_effect=RuntimeError("secret postgres password")), \
                    redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(cli.main(["--retained-report", str(source), "--output", str(output)]), 1)
            self.assertFalse(output.exists())
            self.assertNotIn("password", stderr.getvalue())
            engine.return_value.dispose.assert_called_once()

    def test_exclusive_creation_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "manifest.json"
            with patch.object(cli, "MANIFEST_DIRECTORY", root):
                cli.write_manifest(output, build())
                original = output.read_bytes()
                with self.assertRaises(ValueError):
                    cli.write_manifest(output, {})
                self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
