from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models import Event, FatigueScore, Player, PlayerGameLog, Prop, User
from app.schemas import RestWorkloadOut
from app.services.nba_evidence_service import build_stored_rest_workload
from app.services.fatigue_service import fatigue_label, fatigue_to_dict
from app.services.trend_service import TREND_SPORTS, VERIFIED_LOG_SOURCES, build_history_research, build_line_split, build_line_trends
from app.services.game_log_fields import provider_season
from app.services.sports_statistics import build_sport_summary, validate_season
from app.services.statistics_coverage import player_statistics_coverage
from app.services.nba_matchup_context import build_stored_matchup_context
from app.services.game_identity_service import game_start, prop_context, upcoming_game_filter
from app.services.offer_service import available_offer_filter, eligible_offers, odds_freshness, primary_prices, best_line_fields, primary_offer_status, utc

router = APIRouter()

@router.get("/")
def list_players(db: Session = Depends(get_db)):
    players = db.query(Player).order_by(Player.name).all()
    return [
        {
            "id":    str(p.id),
            "name":  p.name,
            "team":  p.team,
            "sport": p.sport,
        }
        for p in players
    ]


def get_live_player_props(db: Session, player_id: str) -> list[Prop]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
    props = (
        db.query(Prop)
        .options(joinedload(Prop.player), joinedload(Prop.event), joinedload(Prop.book_offers))
        .filter(Prop.player_id == player_id)
        .filter(Prop.is_active == True)
        .filter(Prop.book_offers.any(available_offer_filter()))
        .filter(upcoming_game_filter(cutoff))
        .order_by(Prop.game_time, Prop.prop_type, Prop.line, Prop.id)
        .all()
    )
    return sorted(
        [prop for prop in props if game_start(prop) and utc(game_start(prop)) >= utc(cutoff)
         and eligible_offers(prop, cutoff)],
        key=lambda prop: (utc(game_start(prop)), prop.prop_type, prop.line, str(prop.id)),
    )


def serialize_player_summary(
    db: Session,
    player: Player,
    include_trends: bool = False,
) -> dict | None:
    live_props = get_live_player_props(db, player.id)
    if not live_props and not include_trends:
        return None
    game_logs = db.query(PlayerGameLog).filter(PlayerGameLog.player_id == player.id).order_by(PlayerGameLog.game_date.desc()).all()
    coverage = player_statistics_coverage(player, game_logs)
    if not live_props:
        return {"id": str(player.id), "name": player.name, "team": player.team,
                "team_abbr": player.team_abbr, "position": player.position,
                "sport": player.sport, "live_prop_count": 0,
                "next_game_time": None, "top_prop": None, "statistics_coverage": coverage}

    top_prop = live_props[0]
    best_over = best_line_fields(top_prop)["best_over"]
    trends = None
    if include_trends and player.sport in TREND_SPORTS:
        season = provider_season(player.sport, game_start(top_prop))
        trends = build_line_trends(
            player.sport,
            top_prop.prop_type,
            top_prop.line,
            season,
            game_logs,
            before_game=game_start(top_prop),
        )

    movement = serialize_line_movement(db, top_prop)
    return {
        "id": str(player.id),
        "statistics_coverage": coverage,
        "name": player.name,
        "team": player.team,
        "team_abbr": player.team_abbr,
        "position": player.position,
        "sport": player.sport,
        "live_prop_count": len(live_props),
        **odds_freshness(top_prop),
        "next_game_time": utc(game_start(top_prop)).isoformat(),
        "top_prop": {
            "prop_type": top_prop.prop_type,
            "line": top_prop.line,
            "best_over": best_over,
            "line_movement": movement["line_change"] if movement else None,
            "l5_hit_rate": trends["l5"]["hit_rate"] if trends else None,
            "l10_hit_rate": trends["l10"]["hit_rate"] if trends else None,
        },
    }


@router.get("/search")
def search_players(
    q: str = Query("", max_length=80),
    sport: Optional[str] = None,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Player)
        .filter(or_(Player.props.any(
            (Prop.is_active == True)
            & Prop.book_offers.any(available_offer_filter())
            & (Prop.odds_event_id != None)
            & upcoming_game_filter(datetime.now(timezone.utc))
        ), Player.game_logs.any(PlayerGameLog.source.in_([
            "nba_com_stats", "wehoop_wnba_stats", "nhl_web", "nflverse", "mlb_stats_api"
        ]))))
    )
    term = q.strip()
    if term:
        pattern = f"%{term}%"
        query = query.filter(or_(
            Player.name.ilike(pattern),
            Player.team.ilike(pattern),
            Player.team_abbr.ilike(pattern),
        ))
    if sport:
        query = query.filter(Player.sport == sport.upper())

    players = query.order_by(Player.name).limit(limit).all()
    results = [serialize_player_summary(db, player, include_trends=True) for player in players]
    return {"players": [result for result in results if result is not None]}


@router.get("/watchlist")
def get_watchlist(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    player_ids = list(user.fav_players or [])
    if not player_ids:
        return {"players": []}

    players = db.query(Player).filter(Player.id.in_(player_ids)).all()
    player_lookup = {str(player.id): player for player in players}
    results = [
        serialize_player_summary(db, player_lookup[player_id], include_trends=True)
        for player_id in player_ids
        if player_id in player_lookup
    ]
    return {"players": [result for result in results if result is not None]}


@router.post("/{player_id}/follow")
def follow_player(
    player_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not db.query(Player).filter(Player.id == player_id).first():
        raise HTTPException(404, "Player not found")
    favorites = list(user.fav_players or [])
    if player_id not in favorites:
        favorites.append(player_id)
        user.fav_players = favorites
        db.commit()
    return {"ok": True, "following": True}


@router.delete("/{player_id}/follow")
def unfollow_player(
    player_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    favorites = [favorite for favorite in (user.fav_players or []) if favorite != player_id]
    user.fav_players = favorites
    db.commit()
    return {"ok": True, "following": False}


def serialize_research_prop(prop: Prop) -> dict:
    return {
        "id": str(prop.id),
        **primary_offer_status(prop),
        "prop_type": prop.prop_type,
        "line": prop.line,
        **primary_prices(prop),
        "sportsbook": prop.sportsbook,
        **prop_context(prop),
        "opponent": prop.opponent,
        "is_home": prop.is_home,
        **best_line_fields(prop),
    }


def serialize_line_movement(db: Session, prop: Prop) -> dict | None:
    # Existing snapshots contain local capture/ingestion times, including seeded
    # baselines. They cannot establish sportsbook observation history or opening
    # prices. Preserve the nullable legacy contract instead of inventing movement.
    return None


@router.get("/{player_id}/rest-workload", response_model=RestWorkloadOut)
def get_rest_workload(
    player_id: UUID,
    prop_id: Optional[UUID] = None,
    event_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
):
    """Research without an odds prerequisite; never choose a replacement Prop."""
    player = db.query(Player).filter(Player.id == str(player_id)).first()
    if player is None:
        raise HTTPException(404, "Player not found")
    prop, event = None, None
    if prop_id is not None:
        prop = db.query(Prop).options(joinedload(Prop.event)).filter(Prop.id == str(prop_id)).first()
        if prop is None:
            raise HTTPException(404, "Prop not found")
        if str(prop.player_id) != str(player.id):
            raise HTTPException(400, "Prop does not belong to this player")
        if event_id is not None and str(prop.event_id) != str(event_id):
            raise HTTPException(409, "Prop and Event contexts conflict")
        event = prop.event
        if event is not None and event.sport_key != {"NBA": "basketball_nba", "WNBA": "basketball_wnba",
                "MLB": "baseball_mlb", "NFL": "americanfootball_nfl", "NHL": "icehockey_nhl"}.get(player.sport):
            raise HTTPException(400, "Event sport does not match player")
    if event_id is not None:
        event = db.query(Event).filter(Event.id == str(event_id)).first()
        if event is None:
            raise HTTPException(404, "Event not found")
        expected = {"NBA": "basketball_nba", "WNBA": "basketball_wnba", "MLB": "baseball_mlb",
                    "NFL": "americanfootball_nfl", "NHL": "icehockey_nhl"}.get(player.sport)
        if event.sport_key != expected:
            raise HTTPException(400, "Event sport does not match player")
        if prop is None and not db.query(Prop).filter(Prop.player_id == player.id, Prop.event_id == event.id).first():
            raise HTTPException(400, "No authoritative player linkage to this Event")
    logs = db.query(PlayerGameLog).filter(PlayerGameLog.player_id == player.id).all()
    return build_stored_rest_workload(db, player, logs, prop=prop, event=event)


@router.get("/{player_id}/research")
def get_player_research(
    player_id: str,
    prop_type: Annotated[Optional[str], Query(max_length=60)] = None,
    line: Optional[float] = Query(None, allow_inf_nan=False),
    db: Session = Depends(get_db),
    prop_id: Optional[UUID] = None,
    season: Annotated[Optional[str], Query(pattern=r"^\d{4}(-\d{2})?$")] = None,
    competition: Literal["Regular Season", "Playoffs"] = "Regular Season",
    sportsbook: Annotated[Optional[str], Query(max_length=80)] = None,
    offer_line: Annotated[Optional[float], Query(allow_inf_nan=False)] = None,
    side: Literal['over', 'under'] = 'over',
):
    if (sportsbook is not None or offer_line is not None) and prop_id is None:
        raise HTTPException(400, 'Sportsbook line context requires prop_id')
    if prop_id is not None and (prop_type is not None or line is not None):
        raise HTTPException(400, "prop_id cannot be combined with prop_type or line")
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(404, "Player not found")
    if player.sport not in TREND_SPORTS:
        raise HTTPException(400, "Unsupported sport")
    if season is not None:
        try:
            validate_season(player.sport, season)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    live_props = get_live_player_props(db, player_id)
    available_props = [serialize_research_prop(prop) for prop in live_props]
    if prop_id is not None:
        selected = (db.query(Prop)
                    .options(joinedload(Prop.player), joinedload(Prop.event), joinedload(Prop.book_offers))
                    .filter(Prop.id == str(prop_id)).first())
        if selected is None:
            raise HTTPException(404, "Prop not found")
        if str(selected.player_id) != str(player.id):
            raise HTTPException(400, "Prop does not belong to this player")
        selection_source = "prop_id"
    elif prop_type is not None or line is not None:
        # Legacy selectors have no stable prop/event identity. Include unavailable
        # records in ambiguity checks so expiration cannot select another game.
        candidates = (db.query(Prop)
                      .options(joinedload(Prop.player), joinedload(Prop.event), joinedload(Prop.book_offers))
                      .filter(Prop.player_id == player_id).all())
        if prop_type is not None:
            candidates = [prop for prop in candidates if prop.prop_type == prop_type]
        if line is not None:
            candidates = [prop for prop in candidates if abs(prop.line - line) < 0.001]
        if len(candidates) > 1:
            raise HTTPException(409, "Ambiguous player prop selection; use prop_id")
        if not candidates or not eligible_offers(candidates[0]):
            raise HTTPException(400, "Selected player prop is not currently available")
        selected = candidates[0]
        selection_source = "legacy"
    elif not live_props:
        logs = db.query(PlayerGameLog).filter(PlayerGameLog.player_id == player.id).all()
        return {
            "player_id": str(player.id),
            "sport": player.sport,
            "available_props": [],
            "selected_prop": None,
            "selection_source": "default",
            "selection_available": False,
            "line_movement": None,
            "trends": None,
            "splits": None,
            "games": [],
            "history": None,
            "season_summary": build_sport_summary(player, logs, season=season, competition=competition),
            "matchup_context": build_stored_matchup_context(db, player, logs, season=season, competition=competition),
            "rest_workload": build_stored_rest_workload(db, player, logs),
            "message": "No current sportsbook-backed props for this player",
        }
    else:
        selected = live_props[0]
        selection_source = "default"

    selected_start = game_start(selected)
    from app.services.exact_line_research import build_exact_line_research, resolve_research_offer
    exact_selection = resolve_research_offer(selected, db, sportsbook=sportsbook, line=offer_line, side=side)
    summary_season = season
    season = provider_season(player.sport, selected_start or datetime.now(timezone.utc))
    game_logs = (
        db.query(PlayerGameLog)
        .filter(PlayerGameLog.player_id == player_id)
        .order_by(PlayerGameLog.game_date.desc())
        .all()
    )
    historical = build_history_research(
        player.sport,
        selected.prop_type,
        selected.line,
        season,
        game_logs,
        before_game=selected_start,
    )
    results, trends, history = historical["results"], historical["trends"], historical["history"]
    home_results = [item for item in results if item["is_home"] is True]
    away_results = [item for item in results if item["is_home"] is False]
    # These legacy per-prop fields do not establish Event participants or the
    # player's historical side. Suppress a conflicting opponent split rather
    # than guessing from the player's mutable current team.
    selected_opponent = selected.opponent
    event = getattr(selected, "event", None)
    if event is not None and (selected_opponent or "").strip().casefold() not in {
        event.home_team.strip().casefold(), event.away_team.strip().casefold()
    }:
        selected_opponent = None
    opponent_name = (selected_opponent or "").strip().lower()
    opponent_results = [
        item
        for item in results
        if opponent_name and (item.get("opponent") or "").strip().lower() == opponent_name
    ]

    summary_reference = selected_start if getattr(event, 'sport_key', None) == {
        'NBA':'basketball_nba','WNBA':'basketball_wnba','NHL':'icehockey_nhl','NFL':'americanfootball_nfl',
        'MLB':'baseball_mlb'}.get(player.sport) else None
    season_summary = build_sport_summary(player, game_logs, reference=summary_reference,
                                         season=summary_season, competition=competition)
    matchup = build_stored_matchup_context(db, player, game_logs, prop=selected,
                                         season=summary_season, competition=competition)
    exact_line = build_exact_line_research(player, game_logs, market=selected.prop_type,
        line=exact_selection['line'], side=side, summary=season_summary, reference=selected_start,
        season=summary_season, competition=competition,
        opponent_id=(matchup.get('team_context') or {}).get('opponent_id') if matchup else None)
    exact_line['selection'] = exact_selection
    selected_response = serialize_research_prop(selected)
    exact_line['comparison'] = selected_response['comparison']
    exact_line['movement'] = dict(status='unavailable',
        reason='Stored snapshots record ingestion, not verified sportsbook observations. Price and line movement unavailable.')
    exact_line['offer_options'] = [dict(sportsbook=o.sportsbook, line=o.line) for o in selected.book_offers]

    return {
        "player_id": str(player.id),
        "exact_line": exact_line,
        "sport": player.sport,
        "available_props": available_props,
        "selected_prop": selected_response,
        "selection_source": selection_source,
        "selection_available": primary_offer_status(selected)["actionable"],
        "line_movement": serialize_line_movement(db, selected),
        "trends": trends,
        "splits": {
            "home": build_line_split(home_results, season),
            "away": build_line_split(away_results, season),
            "opponent": {
                "name": selected_opponent,
                **build_line_split(opponent_results, season),
            },
        } if trends else None,
        "games": results[:10],
        "history": history,
        "season_summary": season_summary,
        "matchup_context": matchup,
        "rest_workload": build_stored_rest_workload(db, player, game_logs, prop=selected),
        "message": ({"no_history": "No stored player history",
                     "no_valid_market_statistics": "Stored history has no valid statistics for this market",
                     "excluded_history": "Stored history is excluded by historical eligibility rules"}.get(history["status"])
                    if not trends else "Recent history includes previous seasons; the current season has no eligible observations"
                    if not history["current_season_games"] else None),
    }


@router.get("/{player_id}/game-log")
def get_game_log(player_id: str, db: Session = Depends(get_db)):
    """Return verified provider history without synthetic results or sportsbook lines."""
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(404, "Player not found")

    completed_before = datetime.utcnow()
    if player.sport == "MLB":
        completed_before = completed_before.replace(hour=0, minute=0, second=0, microsecond=0)
    logs = (db.query(PlayerGameLog)
            .filter(PlayerGameLog.player_id == player_id)
            .filter(PlayerGameLog.source.in_(VERIFIED_LOG_SOURCES))
            .filter(PlayerGameLog.game_date < completed_before)
            .order_by(PlayerGameLog.game_date.desc()).limit(10).all())
    return {"player_name": player.name,
            "games": [{"game_number": index + 1, "game_date": log.game_date.isoformat(), "opponent": log.opponent,
                       "is_home": log.is_home, "stats": log.stats, "source": log.source,
                       "actual_points": (log.stats or {}).get("points"),
                       "actual_minutes": (log.stats or {}).get("minutes")} for index, log in enumerate(reversed(logs))],
            "note": None if logs else "No verified provider game logs available"}


@router.get("/{player_id}")
def get_player(player_id: str, db: Session = Depends(get_db)):
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(404, "Player not found")

    fs    = db.query(FatigueScore).filter(FatigueScore.player_id == player_id).first()
    props = get_live_player_props(db, player_id)

    return {
        "id":        str(player.id),
        "name":      player.name,
        "team":      player.team,
        "team_abbr": player.team_abbr,
        "position":  player.position,
        "age":       player.age,
        "sport":     player.sport,
        "fatigue":   fatigue_to_dict(fs),
        "props": [
            {
                "id":         str(p.id),
                "prop_type":  p.prop_type,
                "line":       p.line,
                **primary_prices(p),
                **odds_freshness(p),
                **prop_context(p),
                "opponent":   p.opponent,
            }
            for p in props
        ],
    }


@router.get("/{player_id}/fatigue")
def get_fatigue(player_id: str, db: Session = Depends(get_db)):
    fs = db.query(FatigueScore).filter(FatigueScore.player_id == player_id).first()
    if not fs:
        raise HTTPException(404, "No fatigue data for player")
    return fatigue_to_dict(fs)
