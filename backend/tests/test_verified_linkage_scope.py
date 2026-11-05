"""Pinned-domain synthetic fixtures only: no provider or database access."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from app.services.event_link_manifest import _digest, build_event_link_manifest
from app.services import verified_linkage_scope as scope


def evidence():
    event = scope.EVENT_METADATA
    return {"mode": "controlled_smoke", "status": "partial",
            "finished_at": "2026-10-14T19:40:00+00:00",
            "scope": {"event_id": event["provider_event_id"], "sport_key": event["sport_key"]},
            "sport_result": {"source": "odds_api_props", "events_successfully_processed": 1,
                             "sport_key": event["sport_key"]},
            "event": {"id": event["provider_event_id"], "sport_key": event["sport_key"],
                      "home_team": event["home_team"], "away_team": event["away_team"],
                      "commence_time": event["scheduled_start_at"]}}


def fixture():
    event = scope.EVENT_METADATA
    rows = [{"prop_id": prop_id, "player_id": str(UUID(int=1)), "player_name": "Synthetic Athlete",
             "event_id": None, "prop_type": "points", "line": 20.5,
             "odds_sport_key": event["sport_key"], "odds_event_id": event["provider_event_id"],
             "game_time": event["scheduled_start_at"], "sport": "NBA", "team": "Mutable Team",
             "team_abbr": "UNK", "opponent": event["home_team"], "is_home": False}
            for prop_id in sorted(scope.PROP_IDS)]
    report = evidence()
    manifest = build_event_link_manifest(rows, report, evidence_source=str(scope.EVIDENCE_PATH))
    return manifest, report


def resign(manifest):
    manifest["manifest_sha256"] = _digest({key: value for key, value in manifest.items()
                                          if key != "manifest_sha256"})


class VerifiedScopeTests(unittest.TestCase):
    def test_exact_synthetic_scope_validates_without_player_team_inference(self):
        manifest, report = fixture()
        self.assertIsNone(scope.validate_scope(manifest, report))
        self.assertEqual(len(scope.PROP_IDS), 10)
        self.assertEqual(scope.APPROVAL_PHRASE, "LINK-VERIFIED-CELTICS-PISTONS-10")

    def test_approval_scope_constants_are_exact(self):
        self.assertEqual(scope.MANIFEST_FILE_SHA256,
                         "ac101a3d765a982b84d59d08f8cd6de5dcd2fbd8e3fea79684d4adf1f6eac461")
        self.assertEqual(scope.EVIDENCE_FILE_SHA256,
                         "b3be5e25a0322f86414c8ed45ed87170dd997e31707d9d698c207316401882f1")
        self.assertTrue(scope.MANIFEST_PATH.is_absolute())
        self.assertTrue(scope.EVIDENCE_PATH.is_absolute())
        self.assertEqual(scope.EVENT_METADATA["provider_event_id"], "26b036ff107f3c658258eaf4a6f26228")

    def test_missing_extra_substituted_and_duplicate_candidates_rejected(self):
        for alteration in ("missing", "extra", "substituted", "duplicate"):
            manifest, report = fixture()
            if alteration == "missing":
                manifest["candidates"].pop()
            elif alteration == "extra":
                manifest["candidates"].append(deepcopy(manifest["candidates"][0]))
            elif alteration == "substituted":
                manifest["candidates"][0]["prop_id"] = str(UUID(int=100))
            else:
                manifest["candidates"][0]["prop_id"] = manifest["candidates"][1]["prop_id"]
            resign(manifest)
            with self.subTest(alteration=alteration), self.assertRaisesRegex(ValueError, "candidate_scope_conflict"):
                scope.validate_scope(manifest, report)

    def test_wrong_event_identity_participants_schedule_rejected(self):
        for field, value in (("provider", "other"), ("sport_key", "basketball_wnba"),
                             ("provider_event_id", "other"), ("home_team", "Boston Celtics"),
                             ("away_team", "Other"), ("scheduled_start_at", "2026-10-20T19:00:03+00:00")):
            manifest, report = fixture()
            manifest["event"][field] = value
            resign(manifest)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "manifest_event_scope_conflict"):
                scope.validate_scope(manifest, report)

    def test_evidence_conflict_and_invalid_retained_provenance_rejected(self):
        for field, value in (("home_team", "Other"), ("commence_time", "2026-10-20T19:00:03+00:00")):
            manifest, report = fixture()
            report["event"][field] = value
            manifest["evidence"]["sha256"] = _digest(report)
            resign(manifest)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "evidence_event_scope_conflict"):
                scope.validate_scope(manifest, report)
        manifest, report = fixture()
        report["mode"] = "ordinary"
        manifest["evidence"]["sha256"] = _digest(report)
        resign(manifest)
        with self.assertRaisesRegex(ValueError, "invalid_retained_evidence"):
            scope.validate_scope(manifest, report)

    def test_flags_target_limit_rejections_shape_and_source_rejected(self):
        for field, value in (("version", True), ("dry_run", False), ("execution_supported", True),
                             ("target_event_id", str(UUID(int=1))), ("max_candidates", 100),
                             ("rejected", [{"reason": "conflict"}]), ("unresolved_inventory_rows", -1)):
            manifest, report = fixture()
            manifest[field] = value
            resign(manifest)
            with self.subTest(field=field), self.assertRaises(ValueError):
                scope.validate_scope(manifest, report)
        for value in ("other-report.json", str(scope.EVIDENCE_PATH) + ".copy"):
            manifest, report = fixture()
            manifest["evidence"]["source"] = value
            resign(manifest)
            with self.subTest(source=value), self.assertRaisesRegex(ValueError, "evidence_provenance_conflict"):
                scope.validate_scope(manifest, report)

    def test_candidate_identity_side_link_and_player_digest_rejected(self):
        for field, value in (("event_id", str(UUID(int=1))), ("game_time", "2026-10-20T19:00:03+00:00"),
                             ("odds_event_id", "other"), ("odds_sport_key", "basketball_wnba"),
                             ("is_home", True), ("is_home", 0), ("opponent", "UNK"),
                             ("player_identity_sha256", "0" * 64), ("line", True)):
            manifest, report = fixture()
            manifest["candidates"][0]["expected"][field] = value
            resign(manifest)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                scope.validate_scope(manifest, report)

    def test_canonical_digests_enforced(self):
        manifest, report = fixture()
        manifest["manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "manifest_canonical_digest_conflict"):
            scope.validate_scope(manifest, report)
        manifest, report = fixture()
        manifest["evidence"]["sha256"] = "0" * 64
        resign(manifest)
        with self.assertRaisesRegex(ValueError, "evidence_provenance_conflict"):
            scope.validate_scope(manifest, report)

    def test_malformed_shapes_fail_closed(self):
        for manifest, report in ((None, {}), ({}, {}), ([], [])):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                scope.validate_scope(manifest, report)
        manifest, report = fixture()
        manifest["candidates"][0]["expected"]["player"] = None
        resign(manifest)
        with self.assertRaises(ValueError):
            scope.validate_scope(manifest, report)

    def test_boolean_classification_counts_are_rejected(self):
        manifest, report = fixture()
        manifest["classification"]["verified_retained_metadata"]["event_groups"] = True
        resign(manifest)
        with self.assertRaisesRegex(ValueError, "classification_scope_conflict"):
            scope.validate_scope(manifest, report)

    def test_fixed_rejections_have_safe_typed_reason_codes(self):
        self.assertTrue(issubclass(scope.ScopeRejected, ValueError))
        manifest, report = fixture()
        manifest["version"] = 2
        resign(manifest)
        with self.assertRaisesRegex(scope.ScopeRejected, "^invalid_manifest_flags$"):
            scope.validate_scope(manifest, report)

    def test_untrusted_uuid_exception_message_is_normalized(self):
        manifest, report = fixture()
        malicious = "secret-value-should-never-be-in-a-rejection-message"
        manifest["candidates"][0]["expected"]["player"]["player_id"] = malicious
        resign(manifest)
        with self.assertRaisesRegex(scope.ScopeRejected, "^invalid_reviewed_document_shape$") as caught:
            scope.validate_scope(manifest, report)
        self.assertNotIn(malicious, str(caught.exception))

    def test_untrusted_domain_validator_errors_are_normalized(self):
        manifest, report = fixture()
        with patch.object(scope, "validate_event_metadata", side_effect=ValueError("untrusted secret")):
            with self.assertRaisesRegex(scope.ScopeRejected, "^invalid_reviewed_document_shape$"):
                scope.validate_scope(manifest, report)


class ReviewedFileLoaderTests(unittest.TestCase):
    def files(self, root):
        manifest, report = fixture()
        manifest["evidence"]["source"] = str(root / "evidence.json")
        resign(manifest)
        payloads = [json.dumps(manifest).encode(), json.dumps(report).encode()]
        for name, content in zip(("manifest.json", "evidence.json"), payloads):
            (root / name).write_bytes(content)
        return payloads

    def patched(self, root, payloads):
        return patch.multiple(scope, MANIFEST_PATH=root / "manifest.json", EVIDENCE_PATH=root / "evidence.json",
                              MANIFEST_FILE_SHA256=hashlib.sha256(payloads[0]).hexdigest(),
                              EVIDENCE_FILE_SHA256=hashlib.sha256(payloads[1]).hexdigest())

    def test_loader_rereads_fixed_paths_and_returns_verified_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payloads = self.files(root)
            with self.patched(root, payloads):
                result = scope.load_reviewed_files()
                self.assertEqual(result["manifest_path"], str(root / "manifest.json"))
                self.assertEqual(len(result["manifest"]["candidates"]), 10)
                self.assertEqual(result["evidence_file_sha256"], hashlib.sha256(payloads[1]).hexdigest())
                (root / "manifest.json").write_bytes(payloads[0] + b" ")
                with self.assertRaisesRegex(ValueError, "manifest_file_hash_conflict"):
                    scope.load_reviewed_files()

    def test_loader_has_no_path_or_hash_override_inputs(self):
        with self.assertRaises(TypeError):
            scope.load_reviewed_files(manifest_path="alternate.json")

    def test_hash_mismatch_and_missing_file_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payloads = self.files(root)
            with self.patched(root, payloads):
                (root / "evidence.json").write_bytes(payloads[1] + b"\n")
                with self.assertRaisesRegex(ValueError, "evidence_file_hash_conflict"):
                    scope.load_reviewed_files()
                (root / "evidence.json").unlink()
                with self.assertRaisesRegex(ValueError, "evidence_file_unavailable"):
                    scope.load_reviewed_files()

    def test_duplicate_keys_invalid_json_and_nonfinite_numbers_rejected(self):
        for content, reason in ((b'{"version":1,"version":1}', "duplicate_json_key"),
                                (b'{"event":{"id":"a","id":"b"}}', "duplicate_json_key"),
                                (b'{"value":NaN}', "invalid_json_number"),
                                (b"not JSON", "manifest_invalid_json"),
                                (b"\xff", "manifest_invalid_json")):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payloads = self.files(root)
                payloads[0] = content
                (root / "manifest.json").write_bytes(content)
                with self.patched(root, payloads), self.assertRaisesRegex(ValueError, reason):
                    scope.load_reviewed_files()

    def test_size_cap_and_empty_file_rejected(self):
        for content in (b"", b" " * 1000001):
            with self.subTest(size=len(content)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payloads = self.files(root)
                payloads[0] = content
                (root / "manifest.json").write_bytes(content)
                with self.patched(root, payloads), self.assertRaisesRegex(ValueError, "manifest_file_size_bound"):
                    scope.load_reviewed_files()


if __name__ == "__main__":
    unittest.main()
