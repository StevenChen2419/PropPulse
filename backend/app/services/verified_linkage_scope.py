"""Pinned, independently reviewed one-Event/ten-prop authorization scope.

No database or provider access. File hashes cover exact bytes; canonical digests
follow the existing manifest convention. No production loader arguments permit
substitution of the reviewed paths, hashes, Event or prop UUID set.
"""
import hashlib
import json
import math
from pathlib import Path
from uuid import UUID

from app.services.event_backfill import CATEGORIES, retained_event, utc_time
from app.services.event_identity import validate_event_metadata
from app.services.event_link_manifest import _digest


PROP_IDS = frozenset({
    "43275c79-c3a0-4514-9d2f-5962e2f6abb8", "4e7ab0af-ecc4-4660-a119-2e91f6d54e7c",
    "51349f06-b16d-45fc-867b-8a374f2f110a", "63438b06-2fff-4598-929a-5ee10b647078",
    "70b242ae-0fe7-43d1-891d-05ea3aa22fcc", "821aaa73-d200-4e84-92ed-87eca2158cae",
    "c465aef1-28da-4832-8490-d8598082985a", "c7c0ed59-5f36-4867-8a0c-06b133ed5801",
    "d4b7e3ec-f237-49c7-96aa-20c2f076aca0", "d8b32747-8d5b-4475-9b0d-da5c1a53a220",
})
EVENT_METADATA = {"provider": "the_odds_api", "sport_key": "basketball_nba",
                  "provider_event_id": "26b036ff107f3c658258eaf4a6f26228",
                  "home_team": "Detroit Pistons", "away_team": "Boston Celtics",
                  "scheduled_start_at": "2026-10-20T19:00:00+00:00"}
_BACKEND = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (_BACKEND / "data/odds_runs/verification/phase3c-preflight-6fd947b2291442b8a5ab93647a716179/phase3c-proposed-links.json").resolve()
EVIDENCE_PATH = (_BACKEND / "data/odds_runs/811a4445-92ad-4499-ad2e-cf174a2c7c2c.json").resolve()
MANIFEST_FILE_SHA256 = "ac101a3d765a982b84d59d08f8cd6de5dcd2fbd8e3fea79684d4adf1f6eac461"
EVIDENCE_FILE_SHA256 = "b3be5e25a0322f86414c8ed45ed87170dd997e31707d9d698c207316401882f1"
APPROVAL_PHRASE = "LINK-VERIFIED-CELTICS-PISTONS-10"
_MAX_BYTES = 1000000


class ScopeRejected(ValueError):
    """A fixed, bounded rejection code safe for operator-facing diagnostics."""


def _require(condition, reason):
    if not condition:
        raise ScopeRejected(reason)


def _canonical_event(event):
    value = validate_event_metadata(**event)
    value["scheduled_start_at"] = utc_time(value["scheduled_start_at"]).isoformat()
    return value


def _validate_scope(manifest, evidence):
    _require(isinstance(manifest, dict) and isinstance(evidence, dict), "invalid_reviewed_document")
    _require(set(manifest) == {"version", "dry_run", "execution_supported", "evidence", "event",
                              "target_event_id", "max_candidates", "candidates", "rejected",
                              "unresolved_inventory_rows", "classification", "manifest_sha256"},
             "invalid_manifest_shape")
    _require(type(manifest["version"]) is int and manifest["version"] == 1
             and manifest["dry_run"] is True and manifest["execution_supported"] is False,
             "invalid_manifest_flags")
    _require(manifest["target_event_id"] is None and type(manifest["max_candidates"]) is int
             and manifest["max_candidates"] == 10, "invalid_manifest_scope_limit")
    _require(manifest["rejected"] == [] and type(manifest["unresolved_inventory_rows"]) is int
             and manifest["unresolved_inventory_rows"] >= 0, "invalid_manifest_inventory")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    _require(_digest(body) == manifest["manifest_sha256"], "manifest_canonical_digest_conflict")
    _require(manifest["event"] == EVENT_METADATA, "manifest_event_scope_conflict")
    _require(_canonical_event(manifest["event"]) == EVENT_METADATA, "invalid_manifest_event")
    retained = retained_event(evidence)
    _require(retained is not None, "invalid_retained_evidence")
    _require(_canonical_event(retained) == EVENT_METADATA, "evidence_event_scope_conflict")
    _require(manifest["evidence"] == {"source": str(EVIDENCE_PATH), "sha256": _digest(evidence),
                                      "hash_format": "canonical-json-utf8"},
             "evidence_provenance_conflict")
    candidates = manifest["candidates"]
    _require(isinstance(candidates, list) and len(candidates) == 10, "candidate_scope_conflict")
    _require(all(isinstance(item, dict) for item in candidates), "invalid_candidate_shape")
    ids = [item.get("prop_id") for item in candidates]
    _require(all(isinstance(value, str) for value in ids) and len(set(ids)) == 10
             and set(ids) == PROP_IDS, "candidate_scope_conflict")
    for item in candidates:
        _require(set(item) == {"prop_id", "expected", "relationship"}
                 and item["relationship"] == "new_link", "invalid_candidate_relationship")
        expected = item["expected"]
        _require(isinstance(expected, dict) and set(expected) == {
            "event_id", "game_time", "is_home", "line", "odds_event_id", "odds_sport_key",
            "opponent", "player", "player_identity_sha256", "prop_type"}, "invalid_expected_shape")
        _require(expected["event_id"] is None
                 and expected["game_time"] == EVENT_METADATA["scheduled_start_at"]
                 and expected["odds_event_id"] == EVENT_METADATA["provider_event_id"]
                 and expected["odds_sport_key"] == EVENT_METADATA["sport_key"],
                 "candidate_event_identity_conflict")
        _require(type(expected["is_home"]) is bool, "invalid_candidate_home_side")
        opponent = EVENT_METADATA["away_team"] if expected["is_home"] else EVENT_METADATA["home_team"]
        _require(expected["opponent"] == opponent, "candidate_participant_side_conflict")
        _require(type(expected["line"]) in (int, float) and math.isfinite(expected["line"])
                 and isinstance(expected["prop_type"], str) and bool(expected["prop_type"].strip()),
                 "invalid_candidate_market")
        player = expected["player"]
        _require(isinstance(player, dict) and set(player) == {
            "player_id", "player_name", "sport", "team", "team_abbr"}, "invalid_player_shape")
        _require(str(UUID(player["player_id"])) == player["player_id"] and player["sport"] == "NBA"
                 and isinstance(player["player_name"], str) and bool(player["player_name"].strip()),
                 "invalid_player_identity")
        # Mutable team fields are fingerprinted, never used to infer participants.
        _require(_digest(player) == expected["player_identity_sha256"], "player_digest_conflict")
    classification = {category: {"event_groups": 0, "prop_rows": 0} for category in CATEGORIES}
    classification["verified_retained_metadata"] = {"event_groups": 1, "prop_rows": 10}
    _require(manifest["classification"] == classification, "classification_scope_conflict")
    _require(all(type(value) is int for counts in manifest["classification"].values()
                 for value in counts.values()), "classification_scope_conflict")


def validate_scope(manifest, evidence):
    """Pure exact-domain validation; raises bounded ValueError, returns None.

    Raw-file authentication belongs to load_reviewed_files. This pure validator
    verifies canonical integrity and domain shape, not arbitrary file provenance.
    """
    try:
        _validate_scope(manifest, evidence)
    except ScopeRejected:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        raise ScopeRejected("invalid_reviewed_document_shape") from None


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "duplicate_json_key")
        value[key] = item
    return value


def _invalid_constant(_value):
    raise ScopeRejected("invalid_json_number")


def _load_exact(path, expected_sha256, label):
    try:
        with path.open("rb") as source:
            content = source.read(_MAX_BYTES + 1)
    except OSError:
        raise ScopeRejected(f"{label}_file_unavailable") from None
    _require(0 < len(content) <= _MAX_BYTES, f"{label}_file_size_bound")
    actual = hashlib.sha256(content).hexdigest()
    _require(actual == expected_sha256, f"{label}_file_hash_conflict")
    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ScopeRejected(f"{label}_invalid_json") from None


def load_reviewed_files():
    """Reread and authenticate only the exact reviewed files; no input overrides."""
    manifest = _load_exact(MANIFEST_PATH, MANIFEST_FILE_SHA256, "manifest")
    evidence = _load_exact(EVIDENCE_PATH, EVIDENCE_FILE_SHA256, "evidence")
    validate_scope(manifest, evidence)
    return {"manifest": manifest, "evidence": evidence, "manifest_path": str(MANIFEST_PATH),
            "evidence_path": str(EVIDENCE_PATH), "manifest_file_sha256": MANIFEST_FILE_SHA256,
            "evidence_file_sha256": EVIDENCE_FILE_SHA256}
