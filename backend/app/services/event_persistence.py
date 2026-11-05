"""Authoritative Event persistence inside the caller's sport transaction.

No commits, HTTP, player inference, or odds freshness changes. The provider has
no metadata version: conflicting participants are refused, and schedule changes
require an independently approved compare-and-set correction (expected old UTC
start). Normal unversioned ingestion can create/reuse but cannot overwrite times.
"""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models import Event, Prop, gen_uuid
from app.services.event_identity import validate_event_metadata, event_time, link_prop_to_event


class EventConflict(ValueError):
    pass


WRITE_FIELDS = ("events_created", "events_reused", "events_updated", "props_newly_linked",
                "existing_links_reused", "schedule_changes")


def event_report():
    return {"events_parsed": 0, "events_validated": 0, "events_rejected": 0,
            "database_attempts": 0,
            "link_conflicts": 0, "legacy_props_unresolved": 0,
            "attempted": dict.fromkeys(WRITE_FIELDS, 0),
            "committed": dict.fromkeys(WRITE_FIELDS, 0),
            "rolled_back": dict.fromkeys(WRITE_FIELDS, 0),
            "transaction_outcome": "pending", "reasons": {}, "samples": []}


def finish_event_report(report, outcome):
    report["transaction_outcome"] = outcome
    report["committed"] = dict(report["attempted"]) if outcome == "committed" else dict.fromkeys(WRITE_FIELDS, 0)
    report["rolled_back"] = dict(report["attempted"]) if outcome == "rolled_back" else dict.fromkeys(WRITE_FIELDS, 0)


def reject(report, reason, identity=None, *, link=False):
    field = "link_conflicts" if link else "events_rejected"
    report[field] += 1
    report["reasons"][reason] = report["reasons"].get(reason, 0) + 1
    if len(report["samples"]) < 30:
        report["samples"].append({"reason": reason, "provider_event_id": str(identity or "")[:128]})


def provider_metadata(data, sport_key):
    if not isinstance(data, dict) or data.get("sport_key") != sport_key:
        raise EventConflict("event_sport_mismatch")
    try:
        values = validate_event_metadata(provider="the_odds_api", sport_key=sport_key,
            provider_event_id=data.get("id"), home_team=data.get("home_team"),
            away_team=data.get("away_team"), scheduled_start_at=data.get("commence_time"))
        values["scheduled_start_at"] = values["scheduled_start_at"].isoformat() + "Z"
        return values
    except (ValueError, TypeError, OverflowError):
        raise EventConflict("invalid_event_metadata") from None


def upsert_event(db, metadata, *, expected_start=None):
    """Return (Event, created/reused/updated), serializing identity races.

    INSERT ON CONFLICT avoids poisoning the enclosing sport transaction on a
    concurrent unique identity. A row lock serializes metadata CAS and link work.
    An expected_start is operator evidence, never a bookmaker observation time.
    """
    values = validate_event_metadata(**metadata)
    identity = {key: values[key] for key in ("provider", "sport_key", "provider_event_id")}
    dialect = db.get_bind().dialect.name
    insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
    if insert is None:
        raise ValueError("Unsupported Event persistence dialect")
    event_id = gen_uuid()
    statement = insert(Event).values(id=event_id, **values).on_conflict_do_nothing(
        index_elements=[Event.provider, Event.sport_key, Event.provider_event_id])
    db.execute(statement)
    result = db.execute(select(Event).filter_by(**identity).with_for_update()
                        .execution_options(populate_existing=True)).scalar_one()
    if result.id == event_id:
        return result, "created"
    if (result.home_team, result.away_team) != (values["home_team"], values["away_team"]):
        raise EventConflict("event_participants_conflict")
    start = values["scheduled_start_at"]
    if result.scheduled_start_at == start:
        return result, "reused"
    if expected_start is None:
        raise EventConflict("unversioned_schedule_conflict")
    if result.scheduled_start_at != event_time(expected_start, require_timezone=True):
        raise EventConflict("stale_schedule_correction")
    result.scheduled_start_at = start
    # All linked markets, including omitted markets and smoke-excluded markets.
    for prop in db.scalars(select(Prop).where(Prop.event_id == result.id).with_for_update()):
        prop.game_time = start
    db.flush()
    return result, "updated"


def resolve_prop(props, player_id, prop_type, event):
    """No first-match or identity-missing adoption; preserve unresolved records."""
    local = [p for p in props if p.player_id == player_id and p.prop_type == prop_type]
    exact = [p for p in local if p.event_id == event.id or p.odds_event_id == event.provider_event_id]
    if len(exact) > 1:
        raise EventConflict("ambiguous_legacy_identity")
    if exact:
        prop = exact[0]
        if prop.odds_sport_key != event.sport_key or prop.odds_event_id != event.provider_event_id:
            raise EventConflict("legacy_provider_identity_conflict")
        if prop.event_id is not None and prop.event_id != event.id:
            raise EventConflict("known_event_reassignment")
        if prop.event_id is None:
            if type(prop.is_home) is not bool:
                raise EventConflict("legacy_participant_conflict")
            group = [p for p in props if p.odds_event_id == event.provider_event_id]
            if any(p.odds_sport_key != event.sport_key or p.game_time != event.scheduled_start_at for p in group):
                raise EventConflict("legacy_schedule_or_sport_conflict")
            expected_opponent = event.away_team if prop.is_home else event.home_team
            if prop.opponent != expected_opponent:
                raise EventConflict("legacy_participant_conflict")
        return prop
    if any(p.odds_event_id is None and (p.game_time is None or p.game_time == event.scheduled_start_at)
           for p in local):
        raise EventConflict("unverified_legacy_identity")
    return None


def associate_prop(prop, event, report):
    known = prop.event_id is not None
    link_prop_to_event(prop, event)
    report["attempted"]["existing_links_reused" if known else "props_newly_linked"] += 1
