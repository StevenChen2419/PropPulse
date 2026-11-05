"""Bounded, separately authorized ESPN contract audits; no DB or app settings.

Teams/roster URLs are used by team_directory.py. Scoreboard/summary URLs are
unverified audit templates, not operational ingestion contracts. Responses are
never interpreted as sports facts, followed, paginated, or persisted raw.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

import httpx

AUTHORIZATION_PHRASE = "AUTHORIZE BOUNDED ESPN NBA CONTRACT COLLECTION"
REDACTION_POLICY = "credentials_and_private_pii_v1"
BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ENDPOINTS = ("teams", "roster", "scoreboard", "summary")
MAX_RESPONSE_BYTES = 2_000_000
TIMEOUT_SECONDS = 10


class CollectionRejected(ValueError):
    """Reason codes only: never expose response bytes or transport exceptions."""


def _require(condition, reason):
    if not condition:
        raise CollectionRejected(reason)


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"


def _digest(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _checked_output_path(value):
    path = Path(value)
    _require(path.is_absolute() and not str(path).startswith(("\\\\", "//")), "absolute_local_output_path_required")
    _require(not any(part in {".", ".."} or ":" in part for part in path.parts[1:]), "noncanonical_output_path_forbidden")
    # Walk the lexical path before resolve(), which could hide a symlink/junction.
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        _require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                 "symlink_or_reparse_output_path_forbidden")
    _require(not path.exists(), "output_directory_must_be_new")
    _require(path.parent.is_dir(), "output_parent_must_exist")
    return path.resolve(strict=False)


def build_collection_plan(*, start_date, end_date, team_ids=(), game_ids=(), endpoints=(),
                          request_budget=1, min_delay_seconds=1.0, max_retries=0,
                          output_dir, redaction_policy=REDACTION_POLICY):
    """Pure plan construction: inspect paths only; never create files or clients."""
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except (ValueError, TypeError):
        raise CollectionRejected("explicit_iso_nba_dates_required") from None
    _require(start.isoformat() == start_date and end.isoformat() == end_date and 0 <= (end - start).days < 14,
             "date_scope_exceeds_14_days_or_is_invalid")
    _require(type(request_budget) is int and 1 <= request_budget <= 32, "request_budget_must_be_1_to_32")
    _require(type(max_retries) is int and 0 <= max_retries <= 2, "retries_must_be_0_to_2")
    _require(type(min_delay_seconds) in (int, float) and math.isfinite(min_delay_seconds)
             and 1 <= min_delay_seconds <= 60, "delay_must_be_1_to_60_seconds")
    _require(redaction_policy == REDACTION_POLICY, "unsupported_redaction_policy")
    team_ids, game_ids, endpoints = tuple(team_ids), tuple(game_ids), tuple(endpoints)
    for values, limit in ((team_ids, 2), (game_ids, 8)):
        _require(1 <= len(values) <= limit and len(set(values)) == len(values)
                 and all(isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}", value) for value in values),
                 "invalid_or_excessive_explicit_ids")
    _require(bool(endpoints) and len(set(endpoints)) == len(endpoints) and set(endpoints) <= set(ENDPOINTS),
             "explicit_endpoint_allowlist_required")
    _require("roster" not in endpoints or team_ids, "roster_requires_explicit_team_ids")
    _require("summary" not in endpoints or game_ids, "summary_requires_explicit_game_ids")
    requests = []
    for endpoint in ENDPOINTS:
        if endpoint not in endpoints:
            continue
        if endpoint == "teams":
            scopes = [("NBA", BASE_URL + "/teams")]
        elif endpoint == "roster":
            scopes = [(identity, BASE_URL + "/teams/" + identity + "/roster") for identity in sorted(team_ids)]
        elif endpoint == "scoreboard":
            scopes = [((day := start + timedelta(days=index)).isoformat(),
                       BASE_URL + "/scoreboard?dates=" + day.strftime("%Y%m%d")) for index in range((end - start).days + 1)]
        else:
            scopes = [(identity, BASE_URL + "/summary?event=" + identity) for identity in sorted(game_ids)]
        requests.extend({"endpoint": endpoint, "scope_id": identity, "url": url,
                         "contract_status": "repository_used" if endpoint in {"teams", "roster"} else "unverified_contract_audit"}
                        for identity, url in scopes)
    _require(len(requests) <= request_budget, "planned_requests_exceed_attempt_budget")
    plan = {"mode": "dry_run", "provider": "espn", "sport": "NBA",
            "scope": {"start_date": start_date, "end_date": end_date, "team_ids": sorted(team_ids),
                      "game_ids": sorted(game_ids), "endpoints": [name for name in ENDPOINTS if name in endpoints]},
            "limits": {"request_budget": request_budget, "max_retries": max_retries,
                       "min_delay_seconds": float(min_delay_seconds), "timeout_seconds": TIMEOUT_SECONDS,
                       "max_response_bytes": MAX_RESPONSE_BYTES},
            "requests": requests, "output_dir": str(_checked_output_path(output_dir)),
            "redaction_policy": redaction_policy}
    return {**plan, "plan_sha256": _digest(plan)}


_SENSITIVE = ("password", "passwd", "secret", "token", "apikey", "authorization", "cookie", "headers",
              "email", "phone", "fax", "address", "birthdate", "dateofbirth", "dob", "ssn", "socialsecurity",
              "credentials", "connectionstring", "privatekey", "accesskey", "contact", "latitude", "longitude")


def _private_string(value):
    return bool(re.search(r"[a-z][a-z0-9+.-]*://|\bwww\.", value, re.I)
                or re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", value)
                or re.search(r"\+\d[\d ()-]{7,}\d|\(\d{3}\)\s*\d{3}[- ]\d{4}", value)
                or re.search(r"\b(?:Bearer|Basic)\s+\S+|(?:password|secret|api[_-]?key|token)\s*[:=]\s*\S+", value, re.I))


def redact_payload(value):
    """Keep public sports names/IDs/statistics; remove private PII and all URLs.

    Public athlete/team display names are intentional contract-audit data. Links,
    credential-like keys, contact/address/DOB fields and header objects are not.
    No response header is ever copied into an artifact.
    """
    if isinstance(value, dict):
        return {f"[REDACTED_KEY_{index}]" if _private_string(key) else key:
                "[REDACTED]" if _private_string(key) or any(token in re.sub(r"[^a-z0-9]", "", key.lower()) for token in _SENSITIVE)
                else redact_payload(item) for index, (key, item) in enumerate(value.items())}
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str) and _private_string(value):
        return "[REDACTED]"
    return value


def _strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value
    def reject_constant(value):
        raise ValueError("nonfinite number")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject_constant)
    # This also catches a finite JSON token (1e999) parsed as Python infinity.
    _json_bytes(value)
    return value


def _observed(clock):
    value = clock()
    _require(isinstance(value, datetime) and value.tzinfo is not None, "utc_observation_clock_required")
    return value.astimezone(timezone.utc).isoformat()


def _exclusive_json(directory, filename, value):
    # Names are generated locally, never derived from response fields.
    _require(filename == "manifest.json" or re.fullmatch(r"response_[0-9]{3}\.json", filename), "invalid_artifact_name")
    for candidate in (directory, *directory.parents):
        info = candidate.lstat()
        _require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                 "symlink_or_reparse_output_path_forbidden")
    raw = _json_bytes(value)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory / filename, flags, 0o600)
    created = artifact = None
    try:
        created = os.fstat(descriptor)
        artifact = os.fdopen(descriptor, "wb")
        with artifact:
            artifact.write(raw)
    except BaseException:
        try:
            if artifact is None:
                os.close(descriptor)
            else:
                artifact.close()
        except OSError:
            pass
        # Only remove the file this invocation exclusively created. Preserve a
        # pre-existing/replaced path and the original interruption/error.
        try:
            current = (directory / filename).lstat()
            if created is not None and (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                (directory / filename).unlink()
        except OSError:
            pass
        raise
    return {"artifact": filename, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def execute_collection(plan, *, authorization, reviewed_plan_sha256, transport=None,
                       sleep=time.sleep, clock=lambda: datetime.now(timezone.utc), monotonic=time.monotonic):
    """Explicit separate execution authorization; production transport is opt-in.

    Tests supply httpx.MockTransport. Neither plan construction nor CLI dry-run
    creates a client, opens the network, accesses a database, or writes artifacts.
    """
    _require(authorization == AUTHORIZATION_PHRASE, "separate_collection_authorization_required")
    _require(isinstance(plan, dict), "reviewed_plan_required")
    _require(reviewed_plan_sha256 == plan.get("plan_sha256"), "reviewed_plan_digest_mismatch")
    try:
        rebuilt = build_collection_plan(**plan["scope"], request_budget=plan["limits"]["request_budget"],
            min_delay_seconds=plan["limits"]["min_delay_seconds"], max_retries=plan["limits"]["max_retries"],
            output_dir=plan["output_dir"], redaction_policy=plan["redaction_policy"])
    except (KeyError, TypeError, ValueError):
        raise CollectionRejected("reviewed_plan_invalid") from None
    _require(rebuilt == plan, "reviewed_plan_was_modified")
    directory = _checked_output_path(plan["output_dir"])
    observed = _observed(clock)
    directory.mkdir(exist_ok=False)
    manifest = {"collection_version": 1, "plan_sha256": plan["plan_sha256"], "provider": "espn", "sport": "NBA",
                "observed_at": observed, "status": "collecting", "attempts": [],
                "request_attempts": 0, "raw_payloads_retained": False, "redaction_policy": REDACTION_POLICY}
    stopped = False
    failure = None
    try:
        # No redirects, ambient proxy/CA credentials, auth, or transport-level retries.
        with httpx.Client(transport=transport, timeout=httpx.Timeout(TIMEOUT_SECONDS), trust_env=False,
                          follow_redirects=False, auth=None,
                          headers={"Accept": "application/json", "Accept-Encoding": "identity"}) as client:
            for index, request in enumerate(plan["requests"], 1):
                for retry in range(plan["limits"]["max_retries"] + 1):
                    if manifest["request_attempts"] >= plan["limits"]["request_budget"]:
                        stopped = True
                        manifest["status"] = "budget_exhausted"
                        break
                    if manifest["request_attempts"]:
                        sleep(plan["limits"]["min_delay_seconds"])
                    manifest["request_attempts"] += 1
                    attempt = {"request_index": index, "attempt": retry + 1, **request,
                               "observed_at": _observed(clock), "status": "transport_error", "http_status": None}
                    manifest["attempts"].append(attempt)
                    retryable = False
                    client.cookies.clear()
                    try:
                        deadline = monotonic() + TIMEOUT_SECONDS
                        with client.stream("GET", request["url"]) as response:
                            _require(monotonic() <= deadline, "response_deadline_exceeded")
                            # Do not let automatic gzip/br decompression allocate an
                            # unbounded decoded chunk before our byte-limit check.
                            _require(response.headers.get("content-encoding", "identity").strip().lower() == "identity",
                                     "encoded_response_forbidden")
                            attempt["http_status"] = response.status_code
                            if response.status_code == 429:
                                attempt["status"] = "rate_limited"
                            elif 500 <= response.status_code <= 599:
                                attempt["status"], retryable = "server_error", True
                            elif not 200 <= response.status_code <= 299:
                                attempt["status"] = "redirect_forbidden" if 300 <= response.status_code <= 399 else "http_error"
                            else:
                                raw = bytearray()
                                # Avoid chunk-size buffering that could hide a slow
                                # stream from the elapsed-time check between reads.
                                for chunk in response.iter_bytes():
                                    _require(monotonic() <= deadline, "response_deadline_exceeded")
                                    _require(len(raw) + len(chunk) <= MAX_RESPONSE_BYTES, "response_too_large")
                                    raw.extend(chunk)
                                _require(monotonic() <= deadline, "response_deadline_exceeded")
                                payload = redact_payload(_strict_json(bytes(raw)))
                                envelope = {"collection_version": 1, **request, "observed_at": _observed(clock), "payload": payload}
                                attempt.update(_exclusive_json(directory, f"response_{index:03d}.json", envelope), status="collected",
                                               observed_at=envelope["observed_at"])
                    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError):
                        attempt["status"], retryable = "safe_transport_timeout_or_connect_failure", True
                    except CollectionRejected:
                        attempt["status"] = "response_or_output_rejected"
                    except (ValueError, UnicodeError, RecursionError):
                        attempt["status"] = "invalid_or_partial_json"
                    except (httpx.HTTPError, OSError):
                        attempt["status"] = "transport_or_output_error"
                    finally:
                        client.cookies.clear()
                    if attempt["status"] == "collected":
                        break
                    if retryable and retry < plan["limits"]["max_retries"]:
                        continue
                    stopped = True
                    manifest["status"] = "stopped"
                    break
                if stopped:
                    break
        if not stopped:
            manifest["status"] = "completed"
    except BaseException as error:
        failure = error
        outcome = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
        manifest["status"] = outcome
        if manifest["attempts"] and manifest["attempts"][-1]["status"] != "collected":
            manifest["attempts"][-1]["status"] = outcome
        raise
    finally:
        if failure is None:
            _exclusive_json(directory, "manifest.json", manifest)
        else:
            # Preserve the original failure if the audit volume is unavailable.
            # No response or exception text is copied into this best-effort audit.
            try:
                _exclusive_json(directory, "manifest.json", manifest)
            except BaseException:
                pass
    return manifest
