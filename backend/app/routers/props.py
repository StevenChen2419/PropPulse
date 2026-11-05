import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.auth import get_optional_user
from app.database import get_db
from app.models import Event, Player, PlayerGameLog, Prop, User
from app.services.offer_service import (available_offer_filter, odds_freshness, eligible_offers,
                                        offer_availability, primary_prices, best_line_fields, utc,
                                        offer_refreshed_at, offer_observation_age)
from app.services.discovery_service import score_discovery_prop, discovery_history_summary, discovery_history_windows
from app.services.fatigue_service import fatigue_to_dict
from app.services.statistics_coverage import player_statistics_coverage
from app.services.ranking_service import rank_props
from app.services.inventory_read_service import read_prop_inventory, read_game_log_inventory
from app.services.trend_service import TREND_SPORTS, build_exact_line_trends
from app.services.game_identity_service import (
    prop_context, game_start, resolve_game, filter_game, inventory, event_context, upcoming_game_filter,
    conflicting_legacy_namespaces, legacy_namespace,
)

router = APIRouter()
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INGESTION_STATUS_PATH = os.path.join(BACKEND_DIR, "data", "odds_ingestion_status.json")
SPORT_STATUS_KEYS = {
    "NBA": "basketball_nba",
    "WNBA": "basketball_wnba",
    "NFL": "americanfootball_nfl",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
}
EASTERN = ZoneInfo("America/New_York")


def eastern_day_priority(game_time: Optional[datetime], now_utc: datetime) -> int:
    if game_time is None:
        return 2
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    game_utc = game_time.replace(tzinfo=timezone.utc) if game_time.tzinfo is None else game_time
    game_date = game_utc.astimezone(EASTERN).date()
    today = now_utc.astimezone(EASTERN).date()
    if game_date == today:
        return 0
    return 1 if game_date > today else 2


def read_ingestion_status():
    if not os.path.exists(INGESTION_STATUS_PATH):
        return {
            "source": "not_refreshed",
            "fallback_used": True,
            "message": "Run python scripts/fetch_odds.py",
        }

    try:
        with open(INGESTION_STATUS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        return {
            "source": "status_error",
            "fallback_used": True,
            "message": "Run python scripts/fetch_odds.py",
            "errors": ["Could not read ingestion status"],
        }


@router.get("/ingestion-status")
def get_ingestion_status(db: Session = Depends(get_db)):
    status = read_ingestion_status()
    now = datetime.now(timezone.utc)
    props = db.query(Prop).options(joinedload(Prop.book_offers), joinedload(Prop.player),
                                   joinedload(Prop.event)).filter(
        Prop.is_active == True, Prop.book_offers.any(available_offer_filter(now))).all()
    eligible = [prop for prop in props if eligible_offers(prop, now)]
    freshness = [odds_freshness(prop, now) for prop in eligible]
    current = "last_known" if any(d["source"] == "last_known" for d in freshness) else "live" if freshness else "unavailable"
    current_offer_status = max(freshness, key=lambda d: d["observation_age_seconds"], default={
        "actionable": False, "availability": "market_unavailable", "source": "unavailable"})
    current_offer_status = {**current_offer_status,
                            "game_time": min((utc(game_start(prop)).isoformat() for prop in eligible), default=None)}
    sports = {}
    for sport, key in SPORT_STATUS_KEYS.items():
        previous = (status.get("sports") or {}).get(key, {})
        decisions = [odds_freshness(prop, now) for prop in eligible if prop.player.sport == sport]
        availability = "last_known" if any(d["source"] == "last_known" for d in decisions) else "live" if decisions else "unavailable"
        sports[key] = {**previous, "sport": sport,
                       "ingestion_availability": previous.get("availability"),
                       "availability": availability, "current_prop_count": len(decisions),
                       "cache_age_minutes": max((d["observation_age_seconds"] / 60 for d in decisions), default=None),
                       "evaluated_at": now.isoformat()}
    return {**status, "ingestion_source": status.get("source"), "availability": current,
            "current_offer_status": current_offer_status,
            "sports": sports, "current_prop_count": len(eligible),
            "evaluated_at": now.isoformat(),
            "cache_age_minutes": max((d["observation_age_seconds"] / 60 for d in freshness), default=None)}


def latest_refresh(props):
    return max((value for prop in props if (value := offer_refreshed_at(prop))), default=None)


def load_game_logs(db: Session, props: list[Prop]) -> dict:
    logs_by_player = defaultdict(list)
    player_ids = {
        prop.player_id
        for prop in props
        if prop.player.sport in TREND_SPORTS
    }
    if not player_ids:
        return logs_by_player

    query = (
        db.query(PlayerGameLog)
        .filter(PlayerGameLog.player_id.in_(player_ids))
        .order_by(PlayerGameLog.game_date.desc())
    )
    game_logs = read_game_log_inventory(query) if len(props) > 50 else query.all()
    for game_log in game_logs:
        logs_by_player[game_log.player_id].append(game_log)
    return logs_by_player


def serialize_prop(
    prop: Prop,
    logs_by_player: dict,
    fatigue=None,
    rank_score=None,
    reasons=None,
    line_movement=None,
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": prop.id,
        "statistics_coverage": player_statistics_coverage(prop.player, logs_by_player.get(prop.player_id, []), now=now),
        **odds_freshness(prop, now),
        "player": {
            "id": prop.player.id,
            "name": prop.player.name,
            "team": prop.player.team,
            "team_abbr": prop.player.team_abbr,
            "position": prop.player.position,
            "age": prop.player.age,
            "sport": prop.player.sport,
        },
        "prop_type": prop.prop_type,
        "line": prop.line,
        "line_24h_ago": prop.line_24h_ago,
        **primary_prices(prop, now),
        "sportsbook": prop.sportsbook,
        "odds_event_id": prop.odds_event_id,
        **prop_context(prop),
        "opponent": prop.opponent,
        "is_home": prop.is_home,
        "popularity_count": prop.popularity_count,
        "fatigue": fatigue,
        "rank_score": rank_score,
        "reasons": reasons or [],
        "line_movement": line_movement,
        "trends": build_exact_line_trends(
            prop,
            logs_by_player.get(prop.player_id, []),
        ),
        **best_line_fields(prop, now),
    }


def build_todays_games(
    db: Session,
    sport: Annotated[Optional[str], Query(max_length=12)] = None,
    limit: int = Query(20, ge=1, le=100),
):
    now = datetime.now(timezone.utc)
    q = (
        db.query(Prop)
        .join(Player)
        .options(joinedload(Prop.player), joinedload(Prop.event), joinedload(Prop.book_offers))
        .filter(Prop.is_active == True)
        .filter(Prop.book_offers.any(available_offer_filter()))
        .filter(Prop.odds_event_id != None)
        .filter(upcoming_game_filter(now))
    )
    grouped = {}
    all_inventory = inventory(db)
    conflicts = conflicting_legacy_namespaces(all_inventory)
    key_identities = defaultdict(set)
    for stored in all_inventory:
        key = prop_context(stored)["game_key"]
        identity = ("event", stored.event_id) if stored.event_id else ("legacy", legacy_namespace(stored))
        key_identities[key].add(identity)
    for event in db.query(Event).all():
        key_identities[event_context(event)["game_key"]].add(("event", event.id))
    for prop in read_prop_inventory(q):
        if not eligible_offers(prop, now):
            continue
        context = prop_context(prop)
        if not context["game_key"] or (sport and context["sport"] != sport):
            continue
        if prop.event_id is None and (legacy_namespace(prop) in conflicts
                                     or len(key_identities[context["game_key"]]) > 1):
            continue
        key = ("event", context["event_id"]) if prop.event_id else ("legacy", context["game_key"], legacy_namespace(prop))
        if key not in grouped:
            grouped[key] = {
                **context,
                "has_eligible_props": True,
                "prop_count": 0,
                **odds_freshness(prop, now),
            }
        elif offer_observation_age(prop, now) > grouped[key]["observation_age_seconds"]:
            grouped[key].update(odds_freshness(prop, now))
        grouped[key]["prop_count"] += 1


    games = sorted(
        grouped.values(),
        key=lambda game: (game["game_time"] or "", game["sport"], game["away_team"], game["home_team"]),
    )
    return games[:limit]


@router.get("/todays-games")
def get_todays_games(
    sport: Annotated[Optional[str], Query(max_length=12)] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return build_todays_games(db=db, sport=sport, limit=limit)


@router.get("/games")
def get_games(
    sport: Annotated[Optional[str], Query(max_length=12)] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    games = build_todays_games(db=db, sport=sport, limit=limit)

    return {
        "games": [
            {
                **game,
                "available_props": game["prop_count"],
                "fallback_used": game["source"] == "fallback",
            }
            for game in games
        ],
        "total": len(games),
        "refreshed_at": max((game["refreshed_at"] for game in games if game.get("refreshed_at")), default=None),
    }


@router.get("/feed")
def get_feed(
    limit:     int            = Query(20, ge=1, le=50),
    offset:    Annotated[int, Query(ge=0, le=1000000)] = 0,
    sport:     Annotated[Optional[str], Query(max_length=12)] = None,
    prop_type: Annotated[Optional[str], Query(max_length=60)] = None,
    game_key:  Annotated[Optional[str], Query(max_length=512)] = None,
    user:      Optional[User] = Depends(get_optional_user),
    db:        Session        = Depends(get_db),
    event_id: Optional[UUID] = None,
):
    context = resolve_game(db, event_id, game_key, sport)
    now_utc = datetime.now(timezone.utc)

    # Only real provider events with unexpired sportsbook offers are eligible.
    def base_query():
        q = (
            db.query(Prop)
            .join(Player)
            .options(joinedload(Prop.player), joinedload(Prop.book_offers), joinedload(Prop.event))
            .filter(Prop.is_active == True)
            .filter(Prop.book_offers.any(available_offer_filter()))
            .filter(Prop.odds_event_id != None)
            .filter(upcoming_game_filter(now_utc))
        )
        if prop_type:
            q = q.filter(Prop.prop_type == prop_type)
        if context and context["event_id"]:
            q = q.filter(Prop.event_id == context["event_id"])
        return q

    query = base_query()
    upcoming_props = query.all() if context else read_prop_inventory(query)
    upcoming_props = [prop for prop in upcoming_props if eligible_offers(prop, now_utc)
                      and (not sport or prop_context(prop)["sport"] == sport)]
    all_props = filter_game(upcoming_props, context)

    ranked      = rank_props(all_props, user, db)
    ranked.sort(
        key=lambda item: eastern_day_priority(game_start(item["prop"]), now_utc)
    )
    total       = len(ranked)
    page        = ranked if context else ranked[offset: offset + limit]

    page_props = [item["prop"] for item in page]
    logs_by_player = load_game_logs(db, page_props)

    results = []
    for item in page:
        prop = item["prop"]
        results.append(serialize_prop(
            prop,
            logs_by_player,
            fatigue=item["fatigue"],
            rank_score=item["rank_score"],
            reasons=item["reasons"],
            line_movement=item["line_movement"],
        ))

    return {
        "props":        results,
        "total":        total,
        # Use the persisted odds observation time, never the response clock.
        "refreshed_at": latest_refresh(all_props),
    }


@router.get("/discover")
def get_discover(
    limit: int = Query(20, ge=1, le=50),
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    sport: Annotated[Optional[str], Query(max_length=12)] = None,
    prop_type: Annotated[Optional[str], Query(max_length=60)] = None,
    game_key: Annotated[Optional[str], Query(max_length=512)] = None,
    db: Session = Depends(get_db),
    event_id: Optional[UUID] = None,
    browse: bool = False,
    search: Annotated[Optional[str], Query(max_length=120)] = None,
    sportsbook: Annotated[Optional[str], Query(max_length=80)] = None,
    game_date: Optional[str] = None,
    availability: Optional[str] = None,
    sort: Optional[str] = None,
):
    browsing = browse or any(value is not None for value in (search, sportsbook, game_date, availability, sort))
    if browsing and sport:
        sport = sport.upper()
    context = resolve_game(db, event_id, game_key, sport)
    if browsing:
        from app.services.discover_browse import browse_page
        page, metadata = browse_page(db, limit=limit, offset=offset, sport=sport, prop_type=prop_type,
            search=search, sportsbook=sportsbook, game_date=game_date, availability=availability,
            sort=sort or 'upcoming', context=context)
        logs = load_game_logs(db, page)
        return dict(props=[serialize_prop(prop, logs) for prop in page], **metadata,
                    refreshed_at=latest_refresh(page), supported_sports=sorted(TREND_SPORTS))
    if sport and sport not in TREND_SPORTS:
        raise HTTPException(status_code=400, detail="Unsupported sport")

    now_utc = datetime.now(timezone.utc)
    query = (
        db.query(Prop)
        .join(Player)
        .options(joinedload(Prop.player), joinedload(Prop.book_offers), joinedload(Prop.event))
        .filter(Player.sport.in_(TREND_SPORTS))
        .filter(Prop.is_active == True)
        .filter(Prop.book_offers.any(available_offer_filter()))
        .filter(Prop.odds_event_id != None)
        .filter(upcoming_game_filter(now_utc))
    )
    if prop_type:
        query = query.filter(Prop.prop_type == prop_type)
    if context and context["event_id"]:
        query = query.filter(Prop.event_id == context["event_id"])

    candidates = query.all() if context else read_prop_inventory(query)
    props = [prop for prop in candidates if eligible_offers(prop, now_utc)
             and (not sport or prop_context(prop)["sport"] == sport)]
    props = filter_game(props, context)
    logs_by_player = load_game_logs(db, props)
    discoveries = []
    # Prepare only histories whose eligibility is independent of the request's
    # within-day clock. Price evaluation and scoring below retain the original
    # candidate visitation order, including time-sensitive historical subjects.
    trends_by_subject = {}
    history_cache = {}
    unprepared = object()
    prepared = [unprepared] * len(props)
    preparation_day = now_utc.date()
    by_player = defaultdict(list)
    for encounter, prop in enumerate(props):
        by_player[prop.player_id].append((encounter, prop))
    for player_id, group in by_player.items():
        logs = logs_by_player.get(player_id, [])
        if not all(isinstance(log.game_date, datetime) and utc(log.game_date).date() < preparation_day for log in logs):
            continue
        for encounter, prop in group:
            start = game_start(prop)
            if start is None:
                continue
            subject = (player_id, prop.player.sport, prop.prop_type, prop.line, start, preparation_day)
            if subject not in trends_by_subject:
                trends_by_subject[subject] = build_exact_line_trends(prop, logs, history_cache=history_cache)
            prepared[encounter] = discovery_history_summary(trends_by_subject[subject])
            # These are reuse budgets, never candidate limits. Eviction causes
            # the same calculation to run again; every candidate gets a summary.
            if len(trends_by_subject) > 256:
                trends_by_subject.pop(next(iter(trends_by_subject)))
            if len(history_cache) > 128:
                history_cache.pop(next(iter(history_cache)))
    trends_by_subject.clear()
    history_cache.clear()
    by_player.clear()
    for encounter, prop in enumerate(props):
        line_fields = best_line_fields(prop, include_offers=False)
        if prepared[encounter] is unprepared or datetime.now(timezone.utc).date() != preparation_day:
            trends = build_exact_line_trends(prop, logs_by_player.get(prop.player_id, []))
        else:
            trends = discovery_history_windows(prepared[encounter])
        discovery = score_discovery_prop(
            prop,
            trends,
            line_fields["best_over"],
            line_fields["sportsbook_count"],
        )
        if not discovery:
            continue

        discoveries.append((
            (eastern_day_priority(game_start(prop), now_utc), -discovery["score"],
             -trends["l10"]["decisions"], -line_fields["sportsbook_count"]),
            prop, discovery,
        ))

    discoveries.sort(
        key=lambda item: item[0],
    )
    total = len(discoveries)
    results = []
    for _, prop, discovery in discoveries[offset:offset + limit]:
        serialized = serialize_prop(
            prop, logs_by_player, reasons=discovery["reasons"],
            line_movement=round(prop.line - (prop.line_24h_ago or prop.line), 2),
        )
        serialized.update(discover_score=discovery["score"], discover_reasons=discovery["reasons"],
                          discover_components=discovery["components"])
        results.append(serialized)
    return {
        "props": results,
        "total": total,
        "refreshed_at": latest_refresh(props),
        "supported_sports": sorted(TREND_SPORTS),
    }


@router.get("/game")
def get_game_detail(
    game_key: Annotated[Optional[str], Query(max_length=512)] = None,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
    event_id: Optional[UUID] = None,
    sport: Annotated[Optional[str], Query(max_length=12)] = None,
):
    if event_id is None and game_key is None:
        raise HTTPException(400, "Supply event_id or game_key")
    context = resolve_game(db, event_id, game_key, sport)
    feed = get_feed(
        limit=50,
        offset=0,
        sport=context["sport"],
        prop_type=None,
        game_key=None if context["event_id"] else game_key,
        event_id=context["event_id"],
        user=user,
        db=db,
    )
    if feed["total"] == 0:
        if not context["event_id"]:
            raise HTTPException(status_code=404, detail="No live props found for this game")
        return {**context, "props": [], "total_props": 0, "sportsbook_count": 0,
                "has_eligible_props": False, "source": "unavailable", "actionable": False,
                "availability": "market_unavailable", "refreshed_at": None}

    sportsbook_count = len({offer["sportsbook"] for prop in feed["props"]
                            for offer in prop["sportsbook_offers"]})

    oldest = max(feed["props"], key=lambda p: p.get("observation_age_seconds") or 0)
    freshness = {key: oldest[key] for key in (
        "source", "availability", "actionable", "observation_age_seconds", "expires_at", "evaluated_at"
    ) if key in oldest}

    return {
        **context,
        "has_eligible_props": True,
        "total_props": feed["total"],
        **freshness,
        "source": "last_known" if any(p["source"] == "last_known" for p in feed["props"]) else "live",
        "actionable": any(p.get("actionable", False) for p in feed["props"]),
        "availability": "last_known" if any(p["source"] == "last_known" for p in feed["props"]) else "available",
        "sportsbook_count": sportsbook_count,
        "props": feed["props"],
        "refreshed_at": feed["refreshed_at"],
    }
