"""Read-only, evidence-based event classification; never constructs Event records.

Player-derived matchups are diagnostics only. An internally consistent matchup is
not authoritative evidence. Retained metadata is accepted only from the validated
controlled-smoke report format; other report formats remain unsupported.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import text


SPORTS = {
    "basketball_nba": "NBA", "basketball_wnba": "WNBA", "baseball_mlb": "MLB",
    "americanfootball_nfl": "NFL", "icehockey_nhl": "NHL",
}
CATEGORIES = (
    "verified_retained_metadata", "candidate_requires_verification",
    "conflicting_metadata", "missing_provider_identity", "legacy_unknown_origin",
)


def utc_time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def retained_event(report):
    """Validate report provenance/shape and copy only safe event metadata.

    This establishes provenance within locally trusted operator reports, not a
    cryptographic guarantee. Never pass arbitrary user payloads as trusted reports.
    """
    if not isinstance(report, dict):
        return None
    event, scope, result = (report.get(key) for key in ("event", "scope", "sport_result"))
    if (report.get("mode") != "controlled_smoke"
            or report.get("status") not in {"completed", "success", "partial"}
            or not all(isinstance(item, dict) for item in (event, scope, result))
            or result.get("source") != "odds_api_props"
            or not isinstance(result.get("events_successfully_processed"), int)
            or result["events_successfully_processed"] < 1
            or utc_time(report.get("finished_at")) is None):
        return None
    event_id, sport_key = event.get("id"), event.get("sport_key")
    if (not isinstance(event_id, str) or not event_id or len(event_id) > 128
            or not isinstance(sport_key, str) or sport_key not in SPORTS or scope.get("event_id") != event_id
            or scope.get("sport_key") != sport_key or result.get("sport_key") != sport_key):
        return None
    home, away = event.get("home_team"), event.get("away_team")
    start = utc_time(event.get("commence_time"))
    if (not all(isinstance(team, str) and 0 < len(team.strip()) <= 150 for team in (home, away))
            or home == away or start is None):
        return None
    return {"provider": "the_odds_api", "provider_event_id": event_id,
            "sport_key": sport_key, "home_team": home, "away_team": away,
            "scheduled_start_at": start.isoformat()}


def classify_events(rows, metadata=(), sample_limit=30):
    """Classify every prop once, with bounded event-group diagnostic samples.

    Missing identities are grouped by prop UUID because they cannot safely be
    collapsed into events. Category counts expose both groups and prop rows.
    """
    if not isinstance(sample_limit, int) or not 0 <= sample_limit <= 1000:
        raise ValueError("sample_limit must be between 0 and 1000")
    evidence = defaultdict(list)
    for item in metadata:
        evidence[(item["sport_key"], item["provider_event_id"])].append(item)
    groups = defaultdict(list)
    for row in rows:
        identity = (row.get("odds_sport_key"), row.get("odds_event_id"))
        key = identity if all(identity) else (None, str(row["prop_id"]))
        groups[key].append(row)
    counts = {category: {"event_groups": 0, "prop_rows": 0} for category in CATEGORIES}
    diagnostic_counts = Counter()
    sample_buckets = {category: [] for category in CATEGORIES}
    for key, props in sorted(groups.items(), key=lambda item: str(item[0])):
        sport_key, event_id = key
        reasons = []
        starts = {utc_time(row.get("game_time")) for row in props}
        derived = set()
        for row in props:
            team, opponent = row.get("team") or row.get("team_abbr") or "UNK", row.get("opponent") or "TBD"
            away, home = (opponent, team) if row.get("is_home") else (team, opponent)
            derived.add((row.get("sport"), utc_time(row.get("game_time")), away, home))
        if len(derived) > 1:
            reasons.append("inconsistent_player_derived_game_keys")
        if len(starts) > 1:
            reasons.append("conflicting_stored_start_times")
        if None in starts:
            reasons.append("missing_or_invalid_start_time")
        retained = evidence.get((sport_key, event_id), [])
        variants = {(item["home_team"], item["away_team"], item["scheduled_start_at"]) for item in retained}
        if len(variants) > 1:
            reasons.append("conflicting_retained_metadata")
        if retained and starts != {utc_time(retained[0]["scheduled_start_at"])}:
            reasons.append("stored_time_differs_from_retained_metadata")
        if sport_key in SPORTS and any(row.get("sport") != SPORTS[sport_key] for row in props):
            reasons.append("stored_player_sport_conflict")
        if not sport_key:
            category = "missing_provider_identity"
        elif (sport_key not in SPORTS or str(event_id).lower().startswith(("demo", "mock", "synthetic"))):
            category = "legacy_unknown_origin"
            reasons.append("unsupported_identity_origin")
        elif any(reason in reasons for reason in (
                "conflicting_stored_start_times", "conflicting_retained_metadata",
                "stored_time_differs_from_retained_metadata", "stored_player_sport_conflict")) or (
                not retained and "inconsistent_player_derived_game_keys" in reasons):
            category = "conflicting_metadata"
        elif retained:
            category = "verified_retained_metadata"
            reasons.append("validated_controlled_smoke_event_metadata")
        else:
            category = "candidate_requires_verification"
            reasons.append("no_authoritative_retained_metadata")
        counts[category]["event_groups"] += 1
        counts[category]["prop_rows"] += len(props)
        diagnostic_counts.update(reasons)
        if len(sample_buckets[category]) < sample_limit:
            sample = {"category": category, "sport_key": props[0].get("odds_sport_key"),
                      "provider_event_id": props[0].get("odds_event_id"),
                      "example_prop_id": str(props[0]["prop_id"]),
                      "prop_rows": len(props), "derived_key_count": len(derived),
                      "stored_start_time_count": len(starts), "reasons": reasons}
            if category == "verified_retained_metadata":
                sample["verified_event"] = retained[0]
            sample_buckets[category].append(sample)
    # A large missing-identity inventory must not hide verified/conflicting cases.
    samples = []
    for index in range(sample_limit):
        for category in CATEGORIES:
            if index < len(sample_buckets[category]) and len(samples) < sample_limit:
                samples.append(sample_buckets[category][index])
    return {"read_only": True, "provider": "the_odds_api", "categories": counts,
            "total_event_groups": len(groups), "total_prop_rows": sum(len(items) for items in groups.values()),
            "diagnostic_group_counts": dict(sorted(diagnostic_counts.items())),
            "samples": samples, "samples_truncated": len(groups) - len(samples),
            "limitations": ["Player-derived teams never establish authoritative participants.",
                            "No metadata means unresolved; consistent derived keys are insufficient.",
                            "Missing-identity group counts represent individual props, not known events.",
                            "Retained metadata may be stale; schedule conflicts require independent verification."]}


def read_prop_identities(engine, max_rows=100000):
    """Enforce PostgreSQL read-only repeatable-read before reading any app tables.

    No ORM sessions, model imports, application lifespan, commits or DDL. Even a
    query failure rolls back. Refuse oversized inventories instead of silently
    reporting incomplete summary counts.
    """
    if engine.dialect.name != "postgresql":
        raise ValueError("classifier requires PostgreSQL read-only transactions")
    if not isinstance(max_rows, int) or not 1 <= max_rows <= 1000000:
        raise ValueError("invalid row bound")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '15s'"))
            rows = connection.execute(text("""
                SELECT p.id AS prop_id, p.event_id, p.player_id, pl.name AS player_name,
                       p.prop_type, p.line, p.odds_sport_key, p.odds_event_id, p.game_time,
                       p.opponent, p.is_home, pl.sport, pl.team, pl.team_abbr
                FROM props p LEFT JOIN players pl ON pl.id = p.player_id
                ORDER BY p.id LIMIT :row_limit
            """), {"row_limit": max_rows + 1}).mappings().all()
            if len(rows) > max_rows:
                raise ValueError("inventory row bound exceeded; no partial report produced")
            return [dict(row) for row in rows]
        finally:
            transaction.rollback()
