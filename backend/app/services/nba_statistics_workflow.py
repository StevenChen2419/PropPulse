"""Bounded offline NBA import workflow. Transport and collection are separate."""
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Player, PlayerGameLog
from app.services.nba_api_provider import EASTERN, nba_id, normalize_player_statistics, verified_crosswalk
from app.services.nba_statistics_service import import_player_statistics


def database_target(url, *, allow_test_database=False):
    """Return a credential-free exact target, rejecting connection redirection."""
    from sqlalchemy.engine import make_url
    url = make_url(url)
    expected = url.database.startswith("proppulse_test_") if allow_test_database and url.database else url.database == "proppulse"
    if (url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}
            or (not allow_test_database and (url.port or 5432) != 5432) or not expected
            or (url.query and not allow_test_database)):
        raise ValueError("Expected exact loopback PostgreSQL target on port 5432")
    if allow_test_database and set(url.query) - {"options"}:
        raise ValueError("Test connection query may only select an isolated schema")
    return {"host": url.host, "port": url.port or 5432, "database": url.database,
            "username": url.username}


def validate_scope(season, competition, date_from, date_to):
    if season not in {"2025-26", "2026-27"} or competition != "Regular Season":
        raise ValueError("Supported scope: 2025-26 or 2026-27 Regular Season")
    first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
    start = date(2025, 10, 1) if season == "2025-26" else date(2026, 10, 20)
    end = date(int(season[:4]) + 1, 6, 30)
    if not start <= first <= last <= end or last >= datetime.now(EASTERN).date():
        raise ValueError("Date range must be completed Eastern dates within the selected regular season")
    return first, last


def no_completed_collection_dates(season, competition, date_from, date_to):
    """Opening-day absence is an empty collection scope, never game evidence."""
    if season not in {'2025-26', '2026-27'} or competition != 'Regular Season':
        raise ValueError('Supported scope: 2025-26 or 2026-27 Regular Season')
    first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if not date(int(season[:4]), 10, 1) <= first <= last <= date(int(season[:4])+1, 6, 30):
        raise ValueError('Date range must fall within the selected season')
    return season == '2026-27' and (last < date(2026, 10, 20)
        or datetime.now(EASTERN).date() <= date(2026, 10, 20))


def prepare_batch(mapping_doc, artifact_doc, *, season, competition, date_from,
                  date_to, player_ids=None, max_rows=1000):
    first, last = validate_scope(season, competition, date_from, date_to)
    if type(max_rows) is not int or not 1 <= max_rows <= 10000:
        raise ValueError("Maximum combined row scope must be between 1 and 10000")
    if not isinstance(mapping_doc, list) or not 1 <= len(mapping_doc) <= 100:
        raise ValueError("Mapping file must contain 1..100 reviewed or unresolved players")
    selected = {str(UUID(value)) for value in player_ids} if player_ids is not None else None
    mappings, local_seen, nba_seen, skipped = [], set(), set(), []
    for entry in mapping_doc:
        local, athlete = str(UUID(entry["player_id"])), nba_id(entry["nba_player_id"])
        if local in local_seen or athlete in nba_seen:
            raise ValueError("Duplicate/conflicting player mapping, including unreviewed entries")
        local_seen.add(local)
        nba_seen.add(athlete)
        if entry.get("review_status") not in {"verified", "candidate", "unresolved"}:
            raise ValueError("Mapping review_status must be verified, candidate or unresolved")
        if not isinstance(entry.get("player_name"), str) or not entry["player_name"].strip():
            raise ValueError("Mapping requires a player name for review")
        if selected is not None and local not in selected:
            continue
        if entry["review_status"] != "verified":
            skipped.append({"player_id": local, "reason": "Identity is " + entry["review_status"] + "; independently reviewed association required"})
            continue
        mappings.append(dict(entry, player_id=local, nba_player_id=athlete))
    if selected is not None and not selected <= local_seen:
        raise ValueError("Selected player UUID is absent from the reviewed mapping file")
    scope = dict(season=season, competition=competition, date_from=date_from, date_to=date_to)
    if any(artifact_doc.get(key) != value for key, value in scope.items()):
        raise ValueError("Provider artifact scope differs from requested scope")
    responses = artifact_doc.get("responses")
    if not isinstance(responses, list):
        raise ValueError("Provider artifact requires a responses list")
    response_map = {}
    for response in responses:
        identity = nba_id(response["nba_player_id"])
        if identity in response_map:
            raise ValueError("Duplicate provider response")
        response_map[identity] = response
    if set(response_map) != {entry["nba_player_id"] for entry in mappings}:
        raise ValueError("Artifact responses must exactly match selected verified mappings")
    players, total = [], 0
    for entry in mappings:
        response = response_map[entry["nba_player_id"]]
        observed = datetime.fromisoformat(response["observed_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None or observed > datetime.now(timezone.utc):
            raise ValueError("Provider observation must be timezone-aware and not in the future")
        crosswalk = verified_crosswalk([dict(entry, verified=True)])
        records = normalize_player_statistics(response["payload"], observed_at=observed,
            crosswalk=crosswalk, season=season, competition=competition, max_records=min(max_rows, 1000))
        if any(not first <= date.fromisoformat(record["stats"]["_nba"]["game_date"]) <= last for record in records):
            raise ValueError("Provider game is outside the reviewed date range")
        total += len(records)
        if total > max_rows:
            raise ValueError("Combined statistics batch exceeds approved row scope")
        players.append(dict(entry, payload=response["payload"], observed_at=observed,
                            crosswalk=crosswalk, records=records))
    return dict(scope, players=players, skipped=skipped, total_records=total, max_rows=max_rows)


def _compare(existing, record):
    old = existing.stats.get("_nba", {}) if isinstance(existing.stats, dict) else {}
    new = record["stats"]["_nba"]
    if (existing.source != "nba_com_stats" or existing.sport != "NBA"
            or any(old.get(key) != new[key] for key in ("nba_player_id", "nba_game_id", "season", "competition"))):
        raise ValueError("Existing game identity/source conflicts with NBA import")
    if old.get("observed_at", "") > new["observed_at"]:
        raise ValueError("Older NBA observation cannot overwrite accepted statistics")
    return "unchanged" if all(getattr(existing, key) == value for key, value in record.items()) else "updated"


def run_import(engine, batch, *, execute=False, allow_test_database=False):
    target = database_target(engine.url, allow_test_database=allow_test_database)
    results = []
    with Session(engine, autoflush=False) as db, db.begin():
        if not execute:
            db.execute(text("SET TRANSACTION READ ONLY"))
        actual_database, actual_user = db.execute(text("SELECT current_database(), current_user")).one()
        if actual_database != target["database"] or actual_user != target["username"]:
            raise ValueError("Connected database/user differs from the exact approved target")
        identities = {p["player_id"]: p for p in batch["players"]}
        query = select(Player).where(Player.id.in_(identities)).order_by(Player.id)
        if execute:
            query = query.with_for_update()
        stored_players = {p.id: p for p in db.scalars(query)}
        for identity, entry in identities.items():
            player = stored_players.get(identity)
            if player is None or player.sport != "NBA" or player.name != entry["player_name"]:
                raise ValueError("Mapping must match exact existing NBA Player UUID and review name")
        # Scan accepted NBA identities across all games: a new game must not hide
        # an existing contradictory NBA-person/local-UUID association.
        stored = list(db.scalars(select(PlayerGameLog).where(
            (PlayerGameLog.source == "nba_com_stats") | PlayerGameLog.player_id.in_(identities))))
        by_game = {(log.player_id, log.external_game_id): log for log in stored}
        for log in stored:
            metadata = log.stats.get("_nba", {}) if isinstance(log.stats, dict) else {}
            athlete = metadata.get("nba_player_id")
            for identity, entry in identities.items():
                if ((log.player_id == identity and athlete is not None and athlete != entry["nba_player_id"])
                        or (athlete == entry["nba_player_id"] and log.player_id != identity)):
                    raise ValueError("Stored NBA identity conflicts with reviewed player association")
        # All players in a provider game must agree on its season, calendar date
        # and pair of teams, even if their statistics came from different files.
        incoming = [record for entry in batch["players"] for record in entry["records"]]
        touched_games = {record["external_game_id"] for record in incoming}
        contexts = {}
        for record in [dict(external_game_id=log.external_game_id, stats=log.stats)
                       for log in stored if log.external_game_id in touched_games] + incoming:
            metadata = record["stats"].get("_nba", {})
            if not metadata:
                continue  # The per-row source check below rejects actual collisions.
            context = (metadata.get("season"), metadata.get("competition"),
                       metadata.get("game_date"),
                       tuple(sorted((str(metadata.get("team_id")), str(metadata.get("opponent_id"))))))
            key = record["external_game_id"]
            if key in contexts and contexts[key] != context:
                raise ValueError("Stored NBA game metadata conflicts with incoming statistics")
            contexts[key] = context
        for entry in batch["players"]:
            counts = dict(added=0, updated=0, unchanged=0, records=len(entry["records"]))
            for record in entry["records"]:
                existing = by_game.get((entry["player_id"], record["external_game_id"]))
                counts[_compare(existing, record) if existing else "added"] += 1
            if execute:
                imported = import_player_statistics(db, entry["payload"], observed_at=entry["observed_at"],
                    crosswalk=entry["crosswalk"], season=batch["season"],
                    competition=batch["competition"], max_records=min(batch["max_rows"], 1000))
                counts = dict(added=imported["inserted"], updated=imported["updated"],
                              unchanged=imported["unchanged"], records=imported["records"])
            results.append(dict(player_id=entry["player_id"], nba_player_id=entry["nba_player_id"],
                                player_name=entry["player_name"], **counts))
    return dict(mode="execute" if execute else "dry-run", players=results,
                skipped=batch["skipped"], total_records=batch["total_records"])
