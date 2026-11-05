"""Lightweight, request-local subjects for broad read-only inventory queries.

Keep the caller's exact joined eager-load SELECT, including its row encounter
order. ORM identity tracking is unnecessary for ranking/serialization and creates
large duplicate row buffers before collection de-duplication. Consume the same
Core result in small Python batches and retain one subject per identity instead.
These objects must never be attached to a Session or used by a write path.
"""
from collections import namedtuple
from sqlalchemy import LABEL_STYLE_TABLENAME_PLUS_COL

from app.models import Event, Player, PlayerGameLog, Prop, PropBook


# Tuple-backed records avoid a per-row attribute dictionary. All callers are
# read-only; only each prop's offer list is assembled during materialization.
_PropValues = namedtuple("InventoryProp", [c.key for c in Prop.__table__.columns] + ["player", "event", "book_offers"])
_PlayerValues = namedtuple("InventoryPlayer", [c.key for c in Player.__table__.columns])
_EventValues = namedtuple("InventoryEvent", [c.key for c in Event.__table__.columns])
_BookValues = namedtuple("InventoryOffer", [c.key for c in PropBook.__table__.columns])
_LogValues = namedtuple("InventoryGameLog", [c.key for c in PlayerGameLog.__table__.columns])


def read_prop_inventory(query):
    """Read a Prop query eagerly loading player, Event and book_offers.

    No SQL limit, ordering, filter or join is added. Validate the full column
    layout before interpreting rows; fall back to ORM loading for any other
    query shape rather than misassign fields after a loader/schema change.
    """
    # Respect ORM autoflush/identity semantics for any non-read-only caller.
    if query.session.new or query.session.dirty or query.session.deleted:
        return query.all()
    models = (Prop, Player, Event, PropBook)
    fields = [tuple(column.key for column in model.__table__.columns) for model in models]
    prefixes = ("props", "players_1", "events_1", "prop_books_1")
    expected = [f"{prefix}_{field}" for prefix, group in zip(prefixes, fields) for field in group]
    # Query.all() uses this legacy ORM label style. Retain even its labels so
    # PostgreSQL receives the same statement text and binds as the ORM path.
    statement = query.set_label_style(LABEL_STYLE_TABLENAME_PLUS_COL).statement
    result = query.session.connection().execute(statement)
    if list(result.keys()) != expected:
        result.close()
        return query.all()
    subjects, players, events, offers_seen = {}, {}, {}, set()
    sizes = [len(group) for group in fields]
    prop_end = sizes[0]
    player_end = prop_end + sizes[1]
    event_end = player_end + sizes[2]
    try:
        for row in result.yield_per(256):
            prop_id = row[0]
            prop = subjects.get(prop_id)
            if prop is None:
                player_id = row[prop_end]
                player = players.get(player_id)
                if player is None and player_id is not None:
                    player = _PlayerValues(*row[prop_end:player_end])
                    players[player_id] = player
                event_id = row[player_end]
                event = events.get(event_id)
                if event is None and event_id is not None:
                    event = _EventValues(*row[player_end:event_end])
                    events[event_id] = event
                prop = _PropValues(*row[:prop_end], player, event, [])
                subjects[prop_id] = prop
            if row[event_end] is not None and row[event_end] not in offers_seen:
                offers_seen.add(row[event_end])
                prop.book_offers.append(_BookValues(*row[event_end:]))
    finally:
        result.close()
    return list(subjects.values())


def read_game_log_inventory(query):
    """The same ordered historical rows without ORM tracking on broad reads."""
    if query.session.new or query.session.dirty or query.session.deleted:
        return query.all()
    fields = tuple(column.key for column in PlayerGameLog.__table__.columns)
    expected = [f"player_game_logs_{field}" for field in fields]
    result = query.session.connection().execute(
        query.set_label_style(LABEL_STYLE_TABLENAME_PLUS_COL).statement,
    )
    if list(result.keys()) != expected:
        result.close()
        return query.all()
    try:
        subjects = {}
        for row in result.yield_per(256):
            if row[0] not in subjects:
                subjects[row[0]] = _LogValues(*row)
        return list(subjects.values())
    finally:
        result.close()
