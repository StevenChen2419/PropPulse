"""Read-only game context and transitional key resolution. Never creates Events."""
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import and_, or_

from app.models import Event, Player, Prop

SPORTS = {"basketball_nba": "NBA", "basketball_wnba": "WNBA",
          "baseball_mlb": "MLB", "americanfootball_nfl": "NFL", "icehockey_nhl": "NHL"}
UNKNOWN = {"", "unk", "unknown", "tbd", "n/a", "none", "null", "--"}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def game_start(prop):
    event = getattr(prop, "event", None)
    return event.scheduled_start_at if event is not None else getattr(prop, "game_time", None)


def upcoming_game_filter(now):
    """Coarse SQL schedule prefilter using the same precedence as game_start."""
    cutoff = utc(now).replace(tzinfo=None)
    return or_(Prop.event.has(Event.scheduled_start_at >= cutoff),
               and_(Prop.event_id.is_(None), Prop.game_time >= cutoff))


def make_game_key(sport, game_time, away_team, home_team):
    # Retain the original naive-UTC key spelling; serialized timestamps have offsets.
    return "|".join((sport, utc(game_time).replace(tzinfo=None).isoformat(), away_team, home_team))


def parse_game_key(key):
    parts = key.split("|")
    if len(parts) != 4 or not all(parts):
        raise HTTPException(400, "Invalid game key")
    try:
        start = datetime.fromisoformat(parts[1].replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid game key timestamp") from None
    return parts[0], utc(start).isoformat(), parts[2], parts[3]


def normalized_key(key):
    sport, start, away, home = parse_game_key(key)
    return make_game_key(sport, datetime.fromisoformat(start), away, home)


def event_context(event):
    sport = SPORTS[event.sport_key]
    start = utc(event.scheduled_start_at).isoformat()
    return {"event_id": str(event.id), "identity_source": "authoritative", "sport": sport,
            "home_team": event.home_team, "away_team": event.away_team,
            "scheduled_start_at": start, "game_time": start,
            "game_key": make_game_key(sport, event.scheduled_start_at, event.away_team, event.home_team),
            "provider": event.provider, "provider_event_id": event.provider_event_id,
            "sport_key": event.sport_key}


def prop_context(prop):
    event = getattr(prop, "event", None)
    if event is not None:
        return event_context(event)
    player = getattr(prop, "player", None)
    sport = getattr(player, "sport", None)
    team = getattr(player, "team", None) or getattr(player, "team_abbr", None)
    opponent = getattr(prop, "opponent", None)
    side = getattr(prop, "is_home", None)
    start = getattr(prop, "game_time", None)
    valid = (sport and start and isinstance(side, bool) and team and opponent
             and team.strip().casefold() not in UNKNOWN and opponent.strip().casefold() not in UNKNOWN
             and team.strip().casefold() != opponent.strip().casefold())
    away, home = ((opponent, team) if side else (team, opponent)) if valid else (None, None)
    return {"event_id": None, "identity_source": "legacy" if valid else "unresolved",
            "sport": sport, "home_team": home, "away_team": away,
            "scheduled_start_at": utc(start).isoformat() if start else None,
            "game_time": utc(start).isoformat() if start else None,
            "game_key": make_game_key(sport, start, away, home) if valid else None,
            "provider": None, "provider_event_id": None, "sport_key": None}


def inventory(db):
    """Identity evidence for *all* unlinked rows, including inactive/expired.

    Linked identities are represented by the complete Event query in both
    callers, including Events without props. Repeating every linked Prop adds
    no identity evidence. Legacy checks need neither offers nor full Prop ORM
    objects; leave their fields intact for the shared context/namespace policy.
    """
    rows = db.query(Prop.event_id, Prop.odds_sport_key, Prop.odds_event_id,
                    Prop.game_time, Prop.opponent, Prop.is_home, Player).outerjoin(
                        Player, Prop.player_id == Player.id,
                    ).filter(Prop.event_id.is_(None)).all()
    return [SimpleNamespace(event_id=row.event_id, odds_sport_key=row.odds_sport_key,
                            odds_event_id=row.odds_event_id, game_time=row.game_time,
                            opponent=row.opponent, is_home=row.is_home, player=row.Player)
            for row in rows]


def legacy_namespace(prop):
    # A stored opaque ID is evidence of a possible conflict, not verified provenance.
    return (getattr(prop, "odds_sport_key", None), getattr(prop, "odds_event_id", None))


def conflicting_legacy_namespaces(props):
    keys = {}
    for prop in props:
        if getattr(prop, "event_id", None) is None and getattr(prop, "odds_event_id", None):
            keys.setdefault(legacy_namespace(prop), set()).add(prop_context(prop)["game_key"])
    return {namespace for namespace, values in keys.items() if len(values) > 1 or None in values}


def resolve_game(db, event_id=None, game_key=None, sport=None):
    """Resolve against all stored identities, independent of current offer eligibility."""
    if event_id is not None and game_key is not None:
        raise HTTPException(400, "Supply event_id or game_key, not both")
    if event_id is not None:
        event = db.query(Event).filter(Event.id == str(event_id)).first()
        if event is None:
            raise HTTPException(404, "Event not found")
        context = event_context(event)
        if sport and sport != context["sport"]:
            raise HTTPException(400, "Event does not match sport")
        return context
    if game_key is None:
        return None
    key = normalized_key(game_key)
    props = inventory(db)
    matches = [prop for prop in props if prop_context(prop)["game_key"] == key]
    events = db.query(Event).all()
    contexts = {str(event.id): event_context(event) for event in events
                if event_context(event)["game_key"] == key}
    legacy = [prop for prop in matches if prop.event_id is None]
    namespaces = {legacy_namespace(prop) for prop in legacy}
    conflicts = conflicting_legacy_namespaces(props)
    if (len(contexts) + bool(legacy) > 1 or len(namespaces) > 1
            or any(legacy_namespace(prop) in conflicts for prop in legacy)):
        raise HTTPException(409, "Ambiguous legacy game key; use an Event UUID or Prop UUID")
    context = next(iter(contexts.values()), None) or (prop_context(legacy[0]) if legacy else None)
    if context is None:
        raise HTTPException(404, "Game not found")
    if sport and sport != context["sport"]:
        raise HTTPException(400, "Game does not match sport")
    return context


def filter_game(props, context):
    if context is None:
        return props
    if context["event_id"]:
        return [prop for prop in props if str(prop.event_id) == context["event_id"]]
    return [prop for prop in props if prop.event_id is None
            and prop_context(prop)["game_key"] == context["game_key"]]
