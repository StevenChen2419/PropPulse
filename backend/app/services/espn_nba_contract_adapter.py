"""Versioned offline inspection of repository-used ESPN shapes.

This is an audit adapter, not a validated participation parser. No authorized
scoreboard/summary examples exist in this milestone. Candidate identities and
dates must never be promoted to durable final/participation/coverage evidence.
"""
from datetime import datetime, timezone
import hashlib
import json
import re

VERSION = "espn-nba-contract-audit-v1"
KNOWN_ENDPOINTS = {"teams", "roster", "athletes", "gamelog"}
UNVERIFIED_ENDPOINTS = {"scoreboard", "summary"}
BLOCKERS = (
    "No independently validated NBA final/postponed/cancelled status contract.",
    "No independently validated appearance, DNP or inactive contract.",
    "No independently validated complete box-score or schedule contract.",
    "Current roster observations do not establish historical membership.",
    "No audited local Player UUID or odds Event-to-ESPN crosswalk is supplied.",
)


def _identity(value):
    return value if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value) else None


def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return at.astimezone(timezone.utc).isoformat() if at.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def audit_collected_response(envelope):
    """Inspect redacted collector envelopes, without DB/network or raw payload output.

    All accepted shapes are already consumed by existing repository code. A shape
    match does not independently verify ESPN semantics. Unsupported endpoint
    payloads are deliberately opaque, regardless of plausible status/stat fields.
    """
    if not isinstance(envelope, dict) or type(envelope.get("collection_version")) is not int or envelope["collection_version"] != 1:
        raise ValueError("A version-1 collection envelope is required")
    endpoint = envelope.get("endpoint")
    if not isinstance(endpoint, str) or endpoint not in KNOWN_ENDPOINTS | UNVERIFIED_ENDPOINTS:
        raise ValueError("Unsupported contract audit endpoint")
    observed = _instant(envelope.get("observed_at"))
    if observed is None or not isinstance(envelope.get("payload"), dict):
        raise ValueError("Explicit collection observation time and JSON object are required")
    payload = envelope["payload"]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(canonical.encode()) > 2_000_000:
        raise ValueError("Contract audit payload exceeds 2 MB")
    result = {"adapter_version": VERSION, "provider": "espn", "sport": "NBA", "endpoint": endpoint,
              "observed_at": observed, "observation_time_kind": "collector_receipt_not_provider_update",
              "payload_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
              "contract_status": "awaiting_upstream_contract_validation", "candidates": [],
              "evidence_records": [], "safe_to_reconcile": False,
              "verified": {key: None for key in ("final_status", "appearance", "dnp", "inactive",
                  "boxscore_complete", "schedule_complete", "historical_membership")},
              "limitations": list(BLOCKERS), "issues": []}
    if endpoint in UNVERIFIED_ENDPOINTS:
        result["issues"].append("Endpoint response contract is unverified; payload mapping intentionally withheld.")
        return result

    def items(value):
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            result["issues"].append("Missing or malformed repository-used collection; completeness remains unknown.")
            return []
        return value

    def candidate(kind, identity, **fields):
        identity = _identity(identity)
        if identity is None:
            result["issues"].append("Missing or malformed provider identity; no identity is inferred.")
        else:
            result["candidates"].append({"kind": kind, "provider_id": identity, **fields})

    if endpoint == "teams":
        sports = items(payload.get("sports"))
        leagues = items(sports[0].get("leagues")) if sports else []
        teams = items(leagues[0].get("teams")) if leagues else []
        for wrapped in teams:
            team = wrapped.get("team")
            candidate("team_identity", team.get("id") if isinstance(team, dict) else None)
    elif endpoint == "roster":
        team = _identity(envelope.get("scope_id"))
        if team is None:
            result["issues"].append("Requested provider team identity is unavailable.")
        for entry in items(payload.get("athletes")):
            for athlete in items(entry.get("items", [entry])):
                candidate("roster_observation", athlete.get("id"), requested_team_id=team,
                          historical_membership=None)
    elif endpoint == "athletes":
        for athlete in items(payload.get("items")):
            candidate("athlete_identity", athlete.get("id"))
        pages = payload.get("pageCount")
        result["pagination"] = {"reported_page_count": pages if type(pages) is int and pages > 0 else None,
                                "complete": None}
        result["issues"].append("Pagination metadata and one page never establish complete athlete coverage.")
    else:
        events = payload.get("events")
        events = events if isinstance(events, dict) else {}
        names = payload.get("names")
        valid_names = isinstance(names, list) and all(isinstance(name, str) for name in names) and len(set(names)) == len(names)
        for season in items(payload.get("seasonTypes")):
            for category in items(season.get("categories")):
                for row in items(category.get("events")):
                    identity = row.get("eventId")
                    event = events.get(identity, {}) if isinstance(identity, str) else {}
                    event = event if isinstance(event, dict) else {}
                    date = _instant(event.get("gameDate"))
                    stats = row.get("stats")
                    if date is None:
                        result["issues"].append("Missing or timezone-ambiguous gameDate; game time remains unknown.")
                    candidate("game_log_observation", identity, game_at=date,
                              statistic_columns_match=bool(valid_names and isinstance(stats, list) and len(stats) == len(names)),
                              participation=None, final_status=None)
        result["issues"].append("Points, minutes and a past gameDate do not establish finality or verified participation.")
    result["issues"] = sorted(set(result["issues"]))
    return result
