"""Append-only normalized NBA evidence, with no provider transport.

The fixture format is an internal test contract, never an ESPN payload contract.
Writes are restricted to disposable databases; callers own the transaction.
"""
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
import re
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import NBAEvidenceRecord, Player
from app.services.nba_api_provider import ReviewedPlayerCrosswalk
from app.services.rest_workload_service import (
    GameEvidence, ParticipationEvidence, MembershipEvidence, ScheduleCoverageEvidence,
    VerifiedRestEvidence, build_rest_workload,
)

FORMAT = "proppulse-nba-evidence-fixture-v1"
KINDS = {"game", "participation", "athlete", "team", "membership", "coverage"}
EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc
READ_LIMIT = 20000


def _at(value):
    if not isinstance(value, str):
        raise ValueError("Evidence timestamps require explicit timezone offsets")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(UTC)
    except ValueError:
        raise ValueError("Invalid evidence timestamp") from None


def _id(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 300 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid normalized evidence identity")
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _record(raw, now):
    allowed = {"kind", "identity", "source", "observed_at", "payload", "player_id", "team_id", "game_id"}
    if not isinstance(raw, dict) or set(raw) - allowed or not {"kind", "identity", "source", "observed_at", "payload"} <= set(raw):
        raise ValueError("Invalid normalized record shape")
    kind = raw["kind"]
    if kind not in KINDS or not isinstance(raw["payload"], dict):
        raise ValueError("Unsupported evidence kind or payload")
    result = {key: raw.get(key) for key in allowed}
    result.update(identity=_id(raw["identity"]), source=_id(raw["source"]))
    observed = _at(raw["observed_at"])
    if observed > now:
        raise ValueError("Future observations cannot establish evidence")
    result["observed_at"] = observed.isoformat()
    for key in ("team_id", "game_id"):
        if result[key] is not None:
            result[key] = _id(result[key])
    if result["player_id"] is not None:
        result["player_id"] = str(UUID(result["player_id"]))
    if (kind in {"team", "game", "coverage"} and result["player_id"] is not None
            or kind in {"team", "athlete", "membership"} and result["game_id"] is not None
            or kind in {"team", "athlete", "game"} and result["team_id"] is not None):
        raise ValueError("Unexpected identity context for evidence kind")
    payload = dict(raw["payload"])
    shapes = {
        "team": ({"name"}, set()), "athlete": (set(), set()),
        "game": ({"home_team_id", "away_team_id", "scheduled_at", "game_at", "completed_at", "status"}, {"time_precision"}),
        "participation": ({"athlete_id", "state"}, set()),
        "membership": ({"athlete_id", "starts_at", "ends_at"}, set()),
    }
    if kind in shapes:
        required, optional = shapes[kind]
        if not required <= payload.keys() or payload.keys() - required - optional:
            raise ValueError("Invalid normalized payload fields")
    if kind == "team":
        _id(payload["name"])
    if kind in {"athlete", "participation", "membership"} and result["player_id"] is None:
        raise ValueError("Exact local player UUID is required")
    if kind in {"participation", "membership"}:
        _id(payload["athlete_id"])
        if result["team_id"] is None:
            raise ValueError("Provider team identity is required")
    if kind == "game":
        if payload.get("time_precision", "instant") not in {"instant", "eastern_date"}:
            raise ValueError("Unsupported game-time precision")
        if result["game_id"] != result["identity"]:
            raise ValueError("Game identity must equal provider game ID")
        if _id(payload["home_team_id"]) == _id(payload["away_team_id"]):
            raise ValueError("Game participants must differ")
        if payload["status"] not in {"completed", "unfinished", "postponed", "cancelled", "unknown"}:
            raise ValueError("Unknown normalized game status")
        scheduled = _at(payload["scheduled_at"])
        actual = _at(payload["game_at"]) if payload["game_at"] is not None else None
        final = _at(payload["completed_at"]) if payload["completed_at"] is not None else None
        if payload.get("time_precision", "instant") == "eastern_date" and (
                actual is None or actual.astimezone(EASTERN).time() != time.min
                or scheduled != actual or final is not None
                or actual.astimezone(EASTERN).date() >= observed.astimezone(EASTERN).date()):
            raise ValueError("Date-only games require a prior Eastern calendar anchor, not fabricated times")
        if payload["status"] == "completed" and (actual is None or actual >= observed):
            raise ValueError("Final evidence requires actual game time before observation")
        if final is not None and (payload["status"] != "completed" or actual is None or not actual <= final <= observed):
            raise ValueError("Invalid completion chronology")
        payload.update(scheduled_at=scheduled.isoformat(), game_at=actual.isoformat() if actual else None,
                       completed_at=final.isoformat() if final else None)
    if kind == "participation":
        if result["game_id"] is None or payload["state"] not in {"appeared", "dnp", "inactive", "unknown"}:
            raise ValueError("Invalid participation evidence")
    if kind == "membership":
        start = _at(payload["starts_at"])
        end = _at(payload["ends_at"]) if payload["ends_at"] is not None else None
        if start > observed or end is not None and end <= start:
            raise ValueError("Invalid membership interval")
        payload.update(starts_at=start.isoformat(), ends_at=end.isoformat() if end else None)
    if kind == "coverage":
        coverage_type = payload.get("coverage_type")
        common = {"coverage_type", "complete", "reconciled"}
        extra = {"starts_at", "ends_at", "game_ids"} if coverage_type == "schedule" else {"athlete_ids"}
        if coverage_type not in {"schedule", "boxscore"} or set(payload) != common | extra or result["team_id"] is None:
            raise ValueError("Invalid coverage contract")
        if type(payload["complete"]) is not bool or type(payload["reconciled"]) is not bool:
            raise ValueError("Coverage flags require explicit booleans")
        if payload["complete"] and not payload["reconciled"]:
            raise ValueError("Partial reconciliation cannot establish completeness")
        ids_key = "game_ids" if coverage_type == "schedule" else "athlete_ids"
        ids = payload[ids_key]
        if not isinstance(ids, list) or len(ids) > 1000 or len(set(ids)) != len(ids):
            raise ValueError("Invalid coverage inventory")
        payload[ids_key] = sorted(_id(item) for item in ids)
        if coverage_type == "schedule":
            if result["game_id"] is not None:
                raise ValueError("Schedule coverage is a team interval, not a game linkage")
            start, end = _at(payload["starts_at"]), _at(payload["ends_at"])
            if start >= end or payload["complete"] and end > observed:
                raise ValueError("Invalid schedule coverage interval")
            payload.update(starts_at=start.isoformat(), ends_at=end.isoformat())
        elif result["game_id"] is None:
            raise ValueError("Box-score coverage requires game identity")
    result["payload"] = payload
    return result


def _game_time(row):
    return _at(row["payload"]["game_at"] or row["payload"]["scheduled_at"])


def _inventory(rows, team_id, start, end):
    return {row["game_id"] for row in rows if row["kind"] == "game"
            and team_id in {row["payload"]["home_team_id"], row["payload"]["away_team_id"]}
            and start <= _game_time(row) < end}


def _stored(db, provider="espn"):
    rows = db.query(NBAEvidenceRecord).filter(NBAEvidenceRecord.provider == provider,
            NBAEvidenceRecord.sport == "NBA").order_by(NBAEvidenceRecord.id).limit(READ_LIMIT + 1).all()
    if len(rows) > READ_LIMIT:
        raise ValueError("Evidence read bound exceeded; completeness withheld")
    return rows


def _raw(row):
    at = row.observed_at.replace(tzinfo=UTC) if row.observed_at.tzinfo is None else row.observed_at.astimezone(UTC)
    return dict(kind=row.kind, identity=row.identity, player_id=row.player_id, team_id=row.team_id,
                game_id=row.game_id, payload=row.payload, source=row.source, observed_at=at.isoformat())


def _test_target(db):
    bind = db.get_bind()
    url = getattr(bind, "url", None) or bind.engine.url
    if not (url.get_backend_name() == "postgresql" and url.host in {"127.0.0.1", "localhost"}
            and re.fullmatch(r"proppulse_test_[a-z0-9_]+", url.database or "") and not url.query
            or url.get_backend_name() == "sqlite" and url.database in {None, "", ":memory:"} and not url.query):
        raise ValueError("Offline fixtures may write only to disposable test databases")
    if url.get_backend_name() == "postgresql":
        # Engine.url is not the effective libpq target: inherited routing or
        # connect_args can override it. Reject ambient settings before connecting,
        # then check the physical connection without issuing application SQL.
        if any(key.upper().startswith("PG") for key in os.environ):
            raise ValueError("Ambient libpq settings are forbidden for fixture reconciliation")
        connection = db.connection().connection.driver_connection
        if not hasattr(connection, "get_dsn_parameters"):
            raise ValueError("Fixture reconciliation requires an inspectable PostgreSQL connection")
        params = connection.get_dsn_parameters()
        if (params.get("host") != url.host or params.get("hostaddr") not in {None, "", "127.0.0.1", "::1"}
                or params.get("port", "5432") != str(url.port or 5432)
                or params.get("dbname") != url.database
                or url.username is not None and params.get("user") != url.username
                or params.get("service") or params.get("options")):
            raise ValueError("Connected fixture database does not match the explicit disposable target")
    return url


def _boxscore_supports(score, games, athlete_id, observed_at):
    payload = score["payload"]
    if not (payload["complete"] and payload["reconciled"] and athlete_id in payload["athlete_ids"]):
        return False
    score_at = _at(score["observed_at"])
    return bool(games) and score_at <= observed_at and all(
        game["payload"]["status"] == "completed"
        and _at(game["payload"]["completed_at"] or game["observed_at"]) <= score_at for game in games)


def _reconcile(db, manifest, *, sport, start_date, end_date, team_ids, write=False,
               expected_digest=None, now=None, provider="espn", review_provenance=None):
    """Validate an offline fixture; append atomically only with explicit digest gate.

    No commit, no live transport, no default database target. A failed nested
    transaction leaves all previous evidence intact. Changed observations append.
    """
    now = now or datetime.now(UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    if type(write) is not bool:
        raise ValueError("Write authorization must be explicit")
    # Validate fixture routing before issuing even a SELECT on a supplied session.
    url = _test_target(db) if db is not None else None
    start_date, end_date = date.fromisoformat(str(start_date)), date.fromisoformat(str(end_date))
    team_ids = sorted(set(_id(item) for item in team_ids))
    if sport != "NBA" or not 0 <= (end_date - start_date).days < 14 or not 1 <= len(team_ids) <= 8:
        raise ValueError("Explicit NBA scope requires 1-14 dates and 1-8 provider team IDs")
    keys = {"format", "fixture_only", "provider", "sport", "date_start", "date_end", "team_ids", "records"}
    if (not isinstance(manifest, dict) or set(manifest) != keys or manifest["format"] != FORMAT
            or manifest["fixture_only"] is not True or manifest["provider"] != provider
            or manifest["sport"] != sport or manifest["date_start"] != str(start_date)
            or manifest["date_end"] != str(end_date) or sorted(manifest["team_ids"]) != team_ids
            or not isinstance(manifest["records"], list) or not 1 <= len(manifest["records"]) <= 1000):
        raise ValueError("Fixture format or explicit scope mismatch")
    rows = [_record(row, now) for row in manifest["records"]]
    start = datetime.combine(start_date, time.min, EASTERN).astimezone(UTC)
    end = datetime.combine(end_date + timedelta(days=1), time.min, EASTERN).astimezone(UTC)
    for row in rows:
        payload = row["payload"]
        if row["kind"] == "game" and (not start <= _game_time(row) < end
                or not set(team_ids) & {payload["home_team_id"], payload["away_team_id"]}):
            raise ValueError("Game falls outside explicit date/team scope")
        if row["kind"] in {"participation", "membership", "coverage"} and row["team_id"] not in team_ids:
            raise ValueError("Evidence falls outside explicit team scope")
        if row["kind"] == "membership" and (_at(payload["starts_at"]) >= end
                or payload["ends_at"] is not None and _at(payload["ends_at"]) <= start):
            raise ValueError("Membership does not intersect the scope")
        if row["kind"] == "coverage" and payload["coverage_type"] == "schedule" and not (
                start <= _at(payload["starts_at"]) < _at(payload["ends_at"]) <= end):
            raise ValueError("Coverage falls outside explicit date scope")
    existing = [_record(_raw(row), now) for row in _stored(db, provider)] if db is not None else []
    combined = existing + rows
    teams = {row["identity"] for row in combined if row["kind"] == "team"}
    athletes = defaultdict(set)
    for row in combined:
        if row["kind"] == "athlete":
            athletes[row["identity"]].add(row["player_id"])
    games = defaultdict(list)
    for row in combined:
        if row["kind"] == "game":
            games[row["game_id"]].append(row)
    for row in rows:
        payload = row["payload"]
        if row["kind"] == "game" and not {payload["home_team_id"], payload["away_team_id"]} <= teams:
            raise ValueError("Missing durable provider team identity")
        if row["kind"] in {"participation", "membership"} and row["player_id"] not in athletes[payload["athlete_id"]]:
            raise ValueError("Missing exact athlete/player crosswalk")
        if row["team_id"] is not None and row["team_id"] not in teams:
            raise ValueError("Unknown provider team identity")
        if row["kind"] == "participation" and (not games[row["game_id"]] or any(row["team_id"] not in {
                game["payload"]["home_team_id"], game["payload"]["away_team_id"]} for game in games[row["game_id"]])):
            raise ValueError("Participation team/game identity mismatch")
        if row["kind"] == "participation" or row["kind"] == "coverage" and payload["coverage_type"] == "boxscore":
            referenced = games[row["game_id"]]
            if not referenced or any(not start <= _game_time(game) < end or row["team_id"] not in {
                    game["payload"]["home_team_id"], game["payload"]["away_team_id"]} for game in referenced):
                raise ValueError("Referenced game falls outside explicit date/team scope")
        if row["kind"] == "coverage" and payload["complete"]:
            if payload["coverage_type"] == "schedule":
                if set(payload["game_ids"]) != _inventory(combined, row["team_id"], _at(payload["starts_at"]), _at(payload["ends_at"])):
                    raise ValueError("Complete schedule inventory does not reconcile")
            else:
                if not games[row["game_id"]]:
                    raise ValueError("Box-score game is unavailable")
                stated = {item["payload"]["athlete_id"] for item in combined if item["kind"] == "participation"
                          and item["game_id"] == row["game_id"] and item["team_id"] == row["team_id"]
                          and item["payload"]["state"] != "unknown"}
                if not stated <= set(payload["athlete_ids"]):
                    raise ValueError("Complete box score omits declared participation")
    canonical = {**manifest, "team_ids": team_ids, "records": sorted(rows, key=_json)}
    if review_provenance is not None:
        canonical["reviewed_crosswalk_provenance"] = dict(review_provenance)
    digest = hashlib.sha256(_json(canonical).encode()).hexdigest()
    signatures = defaultdict(set)
    for row in combined:
        signatures[(row["kind"], row["identity"])].add(_json({key: row[key] for key in
            ("player_id", "team_id", "game_id", "payload")}))
    conflicts = sum(len(values) > 1 for values in signatures.values())
    report = dict(digest=digest, records=len(rows), inserted=0, duplicates=0,
                  conflicts=conflicts, write=write, database_checked=db is not None, provider_http_attempts=0)
    if not write:
        return report
    if db is None or expected_digest != digest:
        raise ValueError("Write requires a reviewed matching dry-run digest")
    player_ids = {row["player_id"] for row in rows if row["player_id"]}
    known_players = set(db.execute(select(Player.id).where(Player.id.in_(player_ids), Player.sport == "NBA")).scalars())
    if known_players != player_ids:
        raise ValueError("Fixture crosswalk requires existing NBA player UUIDs")
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert = pg_insert if url.get_backend_name() == "postgresql" else sqlite_insert
    with db.begin_nested():
        for row in rows:
            fingerprint = hashlib.sha256(_json(row).encode()).hexdigest()
            values = {**row, "provider": provider, "sport": "NBA", "fingerprint": fingerprint,
                      "observed_at": _at(row["observed_at"]).replace(tzinfo=None),
                      "ingested_at": now.replace(tzinfo=None)}
            statement = insert(NBAEvidenceRecord).values(**values).on_conflict_do_nothing(
                index_elements=["provider", "sport", "kind", "identity", "fingerprint"])
            changed = db.execute(statement).rowcount
            report["inserted"] += changed
            report["duplicates"] += 1 - changed
    return report



def reconcile_fixture(db, manifest, **kwargs):
    """Keep the original ESPN-only synthetic fixture contract unchanged."""
    return _reconcile(db, manifest, provider="espn", **kwargs)


def _supported_nba_record(row):
    """Only actually reviewed Stats contracts may enter operational evidence."""
    source, kind = row.get("source"), row.get("kind")
    payload = row.get("payload", {})
    if not isinstance(payload, dict):
        return False
    return (source == "nba_api.stats.leaguegamelog" and (kind == "team"
                or kind == "game" and payload.get("time_precision") == "eastern_date"
                and payload.get("status") == "completed" and payload.get("completed_at") is None
                and payload.get("scheduled_at") == payload.get("game_at"))
            or source == "nba_api.stats.playergamelog" and (kind == "athlete"
                or kind == "participation" and row.get("payload", {}).get("state") == "appeared"))


def append_normalized_evidence(db, records, *, provider, crosswalk, sport, start_date,
                               end_date, team_ids, write=False, expected_digest=None, now=None):
    """Review/append offline NBA.com facts only to explicitly disposable stores.

    The immutable crosswalk requires explicit review and per-association provenance;
    the dry-run digest binds that provenance. Keys are NBA person IDs and values
    exact existing local UUIDs. No identities are discovered and no network opens.
    Callers own commit/rollback. A matching dry-run digest gates append mode.
    """
    if provider != "nba_com" or not isinstance(crosswalk, ReviewedPlayerCrosswalk):
        raise ValueError("Explicit NBA.com provider and reviewed crosswalk with provenance required")
    mapping = {}
    for athlete, local_id in crosswalk.items():
        if not isinstance(athlete, str) or not athlete.isdecimal() or str(int(athlete)) != athlete or int(athlete) <= 0:
            raise ValueError("Crosswalk requires canonical NBA person IDs")
        mapping[athlete] = str(UUID(str(local_id)))
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Ambiguous NBA player crosswalk")
    if not isinstance(records, list):
        raise ValueError("Normalized records must be a bounded list")
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("Invalid normalized NBA record")
        if not _supported_nba_record(row):
            raise ValueError("Unsupported or unvalidated NBA provider provenance/kind/state")
        athlete = row.get("identity") if row.get("kind") == "athlete" else row.get("payload", {}).get("athlete_id")
        if row.get("player_id") is not None and (athlete not in mapping or str(row["player_id"]) != mapping[athlete]):
            raise ValueError("Missing or conflicting exact NBA player crosswalk")
        # Reserved separator is added only when evidence enters the calculator.
        if any(isinstance(value, str) and ":" in value for value in
               (row.get("identity"), row.get("team_id"), row.get("game_id"), athlete)):
            raise ValueError("NBA identities must not contain provider namespace separators")
    manifest = dict(format=FORMAT, fixture_only=True, provider=provider, sport=sport,
                    date_start=str(start_date), date_end=str(end_date), team_ids=list(team_ids), records=records)
    return _reconcile(db, manifest, provider=provider, sport=sport, start_date=start_date,
                      end_date=end_date, team_ids=team_ids, write=write,
                      expected_digest=expected_digest, now=now, review_provenance=crosswalk.provenance)


def load_verified_evidence(db, player_id, *, now=None):
    """Load independent namespaces; preserve provenance and isolate identities."""
    bundles, notes = [], []
    for provider in ("espn", "nba_com"):
        evidence, provider_notes = _load_provider_evidence(db, player_id, provider=provider, now=now)
        if provider == "nba_com":
            prefix = lambda identity: "nba_com:" + identity
            evidence = VerifiedRestEvidence(
                tuple(replace(item, game_id=prefix(item.game_id), home_team_id=prefix(item.home_team_id),
                              away_team_id=prefix(item.away_team_id)) for item in evidence.games),
                tuple(replace(item, game_id=prefix(item.game_id), team_id=prefix(item.team_id)) for item in evidence.participation),
                tuple(replace(item, team_id=prefix(item.team_id)) for item in evidence.membership),
                tuple(replace(item, team_id=prefix(item.team_id)) for item in evidence.coverage))
        bundles.append(evidence)
        notes.extend(provider_notes)
    return VerifiedRestEvidence(*(tuple(item for bundle in bundles for item in getattr(bundle, field))
                                  for field in ("games", "participation", "membership", "coverage"))), sorted(set(notes))


def _load_provider_evidence(db, player_id, *, provider, now=None):
    """Read retained facts without resolving contradictions or guessing identities."""
    now = now or datetime.now(UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    notes = []
    try:
        stored = _stored(db, provider)
    except ValueError:
        return VerifiedRestEvidence(), ["Evidence inventory exceeds the bounded read; verified coverage is unknown."]
    rows = []
    malformed = False
    for item in stored:
        observed = item.observed_at.replace(tzinfo=UTC) if item.observed_at.tzinfo is None else item.observed_at.astimezone(UTC)
        if observed > now:
            malformed = True
            notes.append("Future-clock retained observations are excluded; exact coverage withheld.")
            continue
        try:
            raw = _record(_raw(item), now)
            if provider == "nba_com" and not _supported_nba_record(raw):
                malformed = True
                notes.append("Unsupported or unvalidated retained NBA provider evidence was excluded.")
                continue
            if provider == "espn" and any(
                    isinstance(value, str) and value.startswith("nba_com:")
                    for value in [raw["identity"], raw["team_id"], raw["game_id"],
                                  *[raw["payload"].get(key) for key in ("home_team_id", "away_team_id", "athlete_id")]]):
                raise ValueError("Reserved provider namespace")
            rows.append(raw)
        except (ValueError, TypeError, KeyError):
            malformed = True
    teams = {row["identity"] for row in rows if row["kind"] == "team"}
    links = defaultdict(set)
    for row in rows:
        if row["kind"] == "athlete":
            links[row["identity"]].add(row["player_id"])
    reverse = defaultdict(set)
    for athlete_id, ids in links.items():
        for local_id in ids:
            reverse[local_id].add(athlete_id)
    selected = [row for row in rows if row["player_id"] == str(player_id)]
    collision = (len(reverse[str(player_id)]) > 1
                 or any(str(player_id) in ids and len(ids) != 1 for ids in links.values()))
    def linked(row):
        return not collision and links[row["payload"]["athlete_id"]] == {str(player_id)} and row["team_id"] in teams
    if any(row["kind"] in {"membership", "participation"} and not linked(row) for row in selected):
        malformed = True
        notes.append("Unresolved retained athlete/team identity prevents exact coverage.")
    membership_variants = defaultdict(set)
    for row in rows:
        if row["kind"] == "membership":
            membership_variants[row["identity"]].add(_json({key: row[key] for key in ("player_id", "team_id", "payload")}))
    members = []
    for row in selected:
        if row["kind"] != "membership" or not linked(row):
            continue
        if len(membership_variants[row["identity"]]) > 1:
            malformed = True
            notes.append("Conflicting dated membership observations are retained and excluded.")
            continue
        members.append(row)
    parts = [row for row in selected if row["kind"] == "participation" and linked(row)]
    relevant_teams = {row["team_id"] for row in members + parts}
    game_rows = [row for row in rows if row["kind"] == "game" and relevant_teams & {
                 row["payload"]["home_team_id"], row["payload"]["away_team_id"]}]
    if any(not {row["payload"]["home_team_id"], row["payload"]["away_team_id"]} <= teams for row in game_rows):
        malformed = True
    game_rows = [row for row in game_rows if {row["payload"]["home_team_id"], row["payload"]["away_team_id"]} <= teams]
    games_by_id = defaultdict(list)
    for row in game_rows:
        games_by_id[row["game_id"]].append(row)
    boxscores = defaultdict(list)
    for row in rows:
        if row["kind"] == "coverage" and row["payload"]["coverage_type"] == "boxscore":
            boxscores[(row["game_id"], row["team_id"])].append(row)
    participation = []
    for row in parts:
        state, payload = row["payload"]["state"], row["payload"]
        scores = boxscores[(row["game_id"], row["team_id"])]
        valid = scores and all(_boxscore_supports(item, games_by_id[row["game_id"]],
                payload["athlete_id"], _at(row["observed_at"])) for item in scores)
        if state in {"dnp", "inactive"} and not valid:
            state = "unknown"
            notes.append("Nonappearance without reconciled box-score coverage remains unknown.")
        participation.append(ParticipationEvidence(str(player_id), row["game_id"], row["team_id"], state,
                              row["source"], _at(row["observed_at"]), provider=provider))
    coverage = []
    schedule_variants = defaultdict(set)
    for row in rows:
        payload = row["payload"]
        if row["kind"] == "coverage" and payload["coverage_type"] == "schedule":
            signature = _json(payload)
            schedule_variants[("identity", row["identity"])].add(signature)
            schedule_variants[(row["team_id"], payload["starts_at"], payload["ends_at"])].add(signature)
    for row in rows:
        payload = row["payload"]
        if row["kind"] != "coverage" or payload["coverage_type"] != "schedule" or row["team_id"] not in relevant_teams:
            continue
        if (len(schedule_variants[("identity", row["identity"])]) > 1
                or len(schedule_variants[(row["team_id"], payload["starts_at"], payload["ends_at"])]) > 1):
            notes.append("Conflicting schedule coverage observations are retained; exact totals withheld.")
            continue
        if payload["complete"] and payload["reconciled"] and not collision and not malformed:
            start, end = _at(payload["starts_at"]), _at(payload["ends_at"])
            if set(payload["game_ids"]) == _inventory(rows, row["team_id"], start, end):
                coverage.append(ScheduleCoverageEvidence(row["team_id"], start, end, True, row["source"], _at(row["observed_at"]), provider=provider))
            else:
                notes.append("Retained schedule coverage no longer reconciles with game inventory; exact totals withheld.")
    if collision:
        notes.append("Conflicting athlete/player crosswalk observations were preserved and excluded.")
    if malformed:
        notes.append("Malformed retained evidence was excluded; exact coverage withheld.")
    games = tuple(GameEvidence(row["game_id"], row["payload"]["home_team_id"], row["payload"]["away_team_id"],
                  _game_time(row), row["payload"]["status"], row["source"], _at(row["observed_at"]),
                  _at(row["payload"]["completed_at"]) if row["payload"]["completed_at"] else None, provider=provider,
                  time_precision=row["payload"].get("time_precision", "instant")) for row in game_rows)
    memberships = tuple(MembershipEvidence(str(player_id), row["team_id"], _at(row["payload"]["starts_at"]),
                        _at(row["payload"]["ends_at"]) if row["payload"]["ends_at"] else None,
                        row["source"], _at(row["observed_at"]), provider=provider) for row in members)
    return VerifiedRestEvidence(games, tuple(participation), memberships, tuple(coverage)), sorted(set(notes))


def build_stored_rest_workload(db, player, logs, *, prop=None, event=None):
    evidence, notes = load_verified_evidence(db, player.id) if player.sport == "NBA" else (None, [])
    result = build_rest_workload(player, logs, prop=prop, event=event, verified_evidence=evidence)
    result["verified"]["notes"] = [note for note in result["verified"]["notes"]
                                   if not note.startswith("Verified schedule and participation retrieval is not connected")]
    if evidence == VerifiedRestEvidence():
        result["verified"]["notes"].append("No usable retained NBA participation evidence is available; verified conclusions remain unknown.")
    result["verified"]["notes"].extend(notes)
    if evidence and (evidence.membership or evidence.participation):
        result["verified"]["notes"].append(
            "Team schedule context uses dated membership at the reference time. Back-to-back is conditional on playing on that date; no selected Event-to-provider game association is verified.")
    return result
