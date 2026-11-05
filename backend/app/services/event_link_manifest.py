"""Pure, dry-run legacy linkage plans. No sessions, writes, provider calls or execution.

The caller supplies a read-only inventory and an operator-trusted retained report.
Store returned manifests in a protected, gitignored local directory: they contain
exact prop/player UUIDs. A SHA256 detects changed evidence; it does not authenticate
an untrusted report. No classification or manifest authorizes a database write.
"""
import hashlib
import json
from uuid import UUID

from app.services.event_backfill import classify_events, retained_event, utc_time
from app.services.event_identity import team_value, validate_event_metadata


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("invalid_inventory_uuid") from None


def _expected(row):
    """Allowlist the stored values whose change invalidates a proposed link."""
    if any(key not in row for key in ("event_id", "opponent", "prop_type", "line")):
        raise ValueError("incomplete_linkage_inventory")
    if not row.get("player_name") or not row.get("player_id"):
        raise ValueError("missing_player_identity")
    start = utc_time(row.get("game_time"))
    if start is None or type(row.get("is_home")) is not bool:
        raise ValueError("missing_stored_identity_evidence")
    player = {key: row.get(key) for key in ("player_name", "sport", "team", "team_abbr")}
    player["player_id"] = _uuid(row["player_id"])
    return {"odds_sport_key": row.get("odds_sport_key"),
            "odds_event_id": row.get("odds_event_id"),
            "game_time": start.isoformat(), "opponent": row.get("opponent"),
            "is_home": row["is_home"],
            "event_id": _uuid(row["event_id"]) if row.get("event_id") else None,
            "prop_type": row.get("prop_type"), "line": row.get("line"),
            "player": player, "player_identity_sha256": _digest(player)}


def build_event_link_manifest(rows, trusted_report, *, evidence_source, target_event_id=None,
                              max_candidates=10):
    """Return exact candidates and expected values, with no implicit execution.

    Only the report's exact provider/sport/event group is considered. The existing
    Phase 3A classifier and Phase 3B validator both must accept its evidence. Player
    team fields are change fingerprints, never authoritative event participants.
    Stored opponent/home-side evidence must exactly match the corresponding
    authoritative participant after whitespace normalization; aliases and unknown
    participants remain unresolved rather than being inferred from player teams.
    The caller must include event_id/player_id/player_name in the inventory (the
    old summary-only inventory is intentionally insufficient for a linkage plan).
    """
    if not isinstance(evidence_source, str) or not evidence_source.strip() or len(evidence_source) > 1024:
        raise ValueError("invalid_evidence_source")
    if type(max_candidates) is not int or not 1 <= max_candidates <= 100:
        raise ValueError("invalid_candidate_bound")
    rows = list(rows)
    if len(rows) > 100000:
        raise ValueError("inventory_bound_exceeded")
    ids = [_uuid(row["prop_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_inventory_prop")
    event = retained_event(trusted_report)
    if event is None:
        raise ValueError("invalid_retained_report")
    try:
        metadata = validate_event_metadata(**event)
    except (ValueError, TypeError):
        raise ValueError("invalid_retained_event") from None
    metadata["scheduled_start_at"] = utc_time(metadata["scheduled_start_at"]).isoformat()
    target = _uuid(target_event_id) if target_event_id is not None else None
    scoped = [row for row in rows if row.get("odds_sport_key") == metadata["sport_key"]
              and row.get("odds_event_id") == metadata["provider_event_id"]]
    classification = classify_events(scoped, [metadata], sample_limit=1)
    verified = classification["categories"]["verified_retained_metadata"]["prop_rows"] == len(scoped)
    candidates, rejected = [], []
    for row in sorted(scoped, key=lambda row: str(row["prop_id"])):
        prop_id = _uuid(row["prop_id"])
        reason = None
        if not verified:
            reason = "unverified_or_conflicting_event_group"
        else:
            try:
                expected = _expected(row)
                if expected["event_id"] is not None and expected["event_id"] != target:
                    reason = "known_event_link_conflict"
                else:
                    try:
                        opponent = team_value(expected["opponent"])
                    except ValueError:
                        reason = "missing_or_unknown_stored_opponent"
                    else:
                        participant = metadata["away_team"] if expected["is_home"] else metadata["home_team"]
                        if opponent != participant:
                            reason = "stored_participant_side_conflict"
            except ValueError as error:
                reason = str(error)
        if reason:
            rejected.append({"prop_id": prop_id, "reason": reason})
        else:
            candidates.append({"prop_id": prop_id, "expected": expected,
                               "relationship": "reused" if expected["event_id"] else "new_link"})
    if len(candidates) > max_candidates:
        raise ValueError("candidate_bound_exceeded")
    manifest = {"version": 1, "dry_run": True, "execution_supported": False,
                "evidence": {"source": evidence_source, "sha256": _digest(trusted_report),
                             "hash_format": "canonical-json-utf8"},
                "event": metadata, "target_event_id": target, "max_candidates": max_candidates,
                "candidates": candidates, "rejected": rejected,
                "unresolved_inventory_rows": len(rows) - len(candidates),
                "classification": classification["categories"]}
    manifest["manifest_sha256"] = _digest(manifest)
    return manifest


def revalidate_event_link_manifest(manifest, fresh_rows, trusted_report, *, evidence_source,
                                   target_event_id=None):
    """Reject changed evidence/records and return a fresh dry-run plan.

    An intervening link to the explicit same target UUID is idempotently accepted;
    any other relationship change is rejected. Unrelated inventory changes do not
    stale a plan. A future executor must revalidate inside its locked transaction;
    this pure function alone cannot protect against subsequent concurrent writes.
    """
    if not isinstance(manifest, dict):
        raise ValueError("invalid_manifest")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if _digest(body) != manifest.get("manifest_sha256"):
        raise ValueError("manifest_integrity_conflict")
    fresh = build_event_link_manifest(fresh_rows, trusted_report, evidence_source=evidence_source,
                                      target_event_id=target_event_id,
                                      max_candidates=manifest["max_candidates"])
    for key in ("version", "dry_run", "execution_supported", "evidence", "event", "target_event_id"):
        if fresh[key] != manifest[key]:
            raise ValueError("stale_manifest_evidence")
    if fresh["rejected"] != manifest["rejected"]:
        raise ValueError("stale_manifest_records")
    original = {item["prop_id"]: item for item in manifest["candidates"]}
    current = {item["prop_id"]: item for item in fresh["candidates"]}
    if set(original) != set(current):
        raise ValueError("stale_manifest_records")
    for prop_id, before in original.items():
        old = dict(before["expected"])
        new = current[prop_id]["expected"]
        if old["event_id"] is None and new["event_id"] == fresh["target_event_id"]:
            old["event_id"] = new["event_id"]
        if old != new:
            raise ValueError("stale_manifest_records")
    return fresh
