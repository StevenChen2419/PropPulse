import json
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import FatigueScore, Player, Prop
from app.schemas import OddsIngestionStatus
from app.services.fatigue_service import fatigue_label

router = APIRouter()
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INGESTION_STATUS_PATH = os.path.join(BACKEND_DIR, "odds_ingestion_status.json")


@router.get("/risk-intelligence")
def risk_intelligence(
    sport: Optional[Literal["NBA", "WNBA", "MLB", "NFL", "NHL"]] = None,
    db: Session = Depends(get_db),
):
    from app.services.risk_intelligence_service import build_risk_intelligence
    return build_risk_intelligence(db, sport=sport)


# ── Existing endpoint (unchanged) ──────────────────────────────────────────────

@router.get("/fatigue-leaderboard")
def fatigue_leaderboard(db: Session = Depends(get_db)):
    scores = (
        db.query(FatigueScore, Player)
        .join(Player, FatigueScore.player_id == Player.id)
        .filter(Player.sport == "NBA")
        .order_by(FatigueScore.fatigue_score.desc())
        .limit(10)
        .all()
    )
    return [
        {
            "player": {
                "id":        str(p.id),
                "name":      p.name,
                "team":      p.team,
                "team_abbr": p.team_abbr,
            },
            "fatigue_score": round(fs.fatigue_score, 3),
            "fatigue_label": fatigue_label(fs.fatigue_score),
            "risk_flags":    fs.risk_flags or [],
            "back_to_back":  fs.back_to_back,
        }
        for fs, p in scores
    ]


# ── New insights endpoint ───────────────────────────────────────────────────────

@router.get("/insights")
def get_insights(db: Session = Depends(get_db)):
    """
    Returns four insight sections computed from existing prop and fatigue data.
    No new ML required. All values come from fields already in the database.

    Sections:
      fatigue_edges        -- top players by fatigue score with their best prop
      line_movers          -- top props by absolute 24h line movement
      back_to_back_tonight -- players flagged as back-to-back tonight
      trending             -- most popular active props by interaction count
    """

    # Single query for all active props with player data loaded.
    active_props = (
        db.query(Prop)
        .join(Player)
        .options(joinedload(Prop.player))
        .filter(Prop.is_active == True)
        .all()
    )

    # Build lookup: player_id -> FatigueScore
    fatigue_by_player = {
        fs.player_id: fs
        for fs in db.query(FatigueScore).all()
    }

    # Build lookup: player_id -> first active prop for that player.
    # Used to attach a representative prop to each player-level insight.
    first_prop_by_player: dict = {}
    for prop in active_props:
        pid = prop.player_id
        if pid not in first_prop_by_player:
            first_prop_by_player[pid] = prop

    # ── Section 1: Fatigue edges ──────────────────────────────────────────────
    # Top 5 players by fatigue score who have at least one active prop.
    # Only include players with fatigue_score >= 0.35 (Medium or above).

    players_ranked_by_fatigue = sorted(
        [
            (pid, fatigue_by_player[pid])
            for pid in first_prop_by_player
            if pid in fatigue_by_player and first_prop_by_player[pid].player.sport == "NBA"
        ],
        key=lambda x: x[1].fatigue_score,
        reverse=True,
    )

    fatigue_edges = []
    for player_id, fs in players_ranked_by_fatigue[:5]:
        if fs.fatigue_score < 0.35:
            continue
        prop   = first_prop_by_player[player_id]
        player = prop.player
        fatigue_edges.append({
            "player": {
                "id":        str(player.id),
                "name":      player.name,
                "team_abbr": player.team_abbr,
            },
            "fatigue_score": round(fs.fatigue_score, 3),
            "fatigue_label": fatigue_label(fs.fatigue_score),
            "back_to_back":  fs.back_to_back,
            "top_flag":      (fs.risk_flags or [""])[0],
            "prop": {
                "id":        str(prop.id),
                "prop_type": prop.prop_type,
                "line":      prop.line,
                "over_odds": prop.over_odds,
            },
        })

    # ── Section 2: Line movers ────────────────────────────────────────────────
    # Top 5 props by absolute line movement (minimum 0.5 move).
    # Only counted when line_24h_ago is populated (after running refresh script).

    movers = []
    for prop in active_props:
        if prop.line_24h_ago is None:
            continue
        movement = round(prop.line - prop.line_24h_ago, 1)
        if abs(movement) < 0.5:
            continue
        movers.append({
            "player_id":    str(prop.player.id),
            "player_name":  prop.player.name,
            "team_abbr":    prop.player.team_abbr,
            "prop_type":    prop.prop_type,
            "line":         prop.line,
            "line_24h_ago": prop.line_24h_ago,
            "movement":     movement,
            "direction":    "up" if movement > 0 else "down",
        })

    movers.sort(key=lambda x: abs(x["movement"]), reverse=True)
    movers = movers[:5]

    # ── Section 3: Back-to-back tonight ──────────────────────────────────────
    # Players with back_to_back == True, sorted by fatigue score descending.

    b2b = []
    for player_id, prop in first_prop_by_player.items():
        fs = fatigue_by_player.get(player_id)
        if prop.player.sport != "NBA" or not fs or not fs.back_to_back:
            continue
        b2b.append({
            "player": {
                "id":        str(prop.player.id),
                "name":      prop.player.name,
                "team_abbr": prop.player.team_abbr,
            },
            "fatigue_score": round(fs.fatigue_score, 3),
            "games_in_7d":   fs.games_in_7d,
        })

    b2b.sort(key=lambda x: x["fatigue_score"], reverse=True)
    b2b = b2b[:5]

    # ── Section 4: Trending ───────────────────────────────────────────────────
    # Top 5 active props by popularity_count.

    sorted_by_pop = sorted(
        active_props,
        key=lambda p: p.popularity_count,
        reverse=True,
    )[:5]

    trending = [
        {
            "player_id":        str(prop.player.id),
            "player_name":      prop.player.name,
            "team_abbr":        prop.player.team_abbr,
            "prop_type":        prop.prop_type,
            "line":             prop.line,
            "popularity_count": prop.popularity_count,
        }
        for prop in sorted_by_pop
    ]

    return {
        "fatigue_edges":         fatigue_edges,
        "line_movers":           movers,
        "back_to_back_tonight":  b2b,
        "trending":              trending,
    }

# ── New model-status endpoint ────────────────────────────────────────────────

@router.get("/ingestion-status", response_model=OddsIngestionStatus)
def get_ingestion_status():
    """
    Return the latest odds ingestion status written by the ingestion scripts.

    This is separate from model-status because odds freshness and ML artifact
    freshness can differ independently.
    """
    if not os.path.exists(INGESTION_STATUS_PATH):
        return {
            "source": "unknown",
            "fallback_used": True,
            "live_games_found": 0,
            "live_props_updated": 0,
            "mock_props_updated": 0,
            "total_props_updated": 0,
            "last_updated": None,
            "message": "Odds ingestion has not run yet. Run python scripts/update_line_movement.py.",
            "matchups": [],
            "status_available": False,
        }

    try:
        with open(INGESTION_STATUS_PATH, "r", encoding="utf-8") as fh:
            status = json.load(fh)
    except Exception as exc:
        return {
            "source": "unknown",
            "fallback_used": True,
            "live_games_found": 0,
            "live_props_updated": 0,
            "mock_props_updated": 0,
            "total_props_updated": 0,
            "last_updated": None,
            "message": "Could not read odds ingestion status",
            "matchups": [],
            "status_available": False,
        }

    status.setdefault("status_available", True)
    status.setdefault("matchups", [])
    return status


@router.get("/model-status")
def get_model_status():
    """
    Returns metadata about the trained XGBoost risk model.
    Reads from ml/models/model_meta.json if it exists.
    Safe to call even if the model has never been trained.
    No DB query needed -- purely file-based.
    """
    # Resolve path relative to this file:
    # rankings.py -> app/routers/ -> app/ -> backend/ -> ml/models/
    meta_path     = os.path.join(BACKEND_DIR, "ml", "models", "model_meta.json")
    artifact_path = os.path.join(BACKEND_DIR, "ml", "models", "risk_model.pkl")

    model_exists = os.path.exists(artifact_path)

    if not os.path.exists(meta_path):
        return {
            "model_exists":   model_exists,
            "trained_at":     None,
            "auc":            None,
            "accuracy":       None,
            "log_loss":       None,
            "feature_count":  None,
            "feature_cols":   [],
            "n_train":        None,
            "n_test":         None,
            "data_source":    "mock",
            "artifact_path":  "ml/models/risk_model.pkl",
            "meta_available": False,
        }

    with open(meta_path, "r") as f:
        meta = json.load(f)

    metrics      = meta.get("metrics", {})
    calibration  = meta.get("calibration", {})
    thresholds   = calibration.get("risk_thresholds", {})

    return {
        "model_exists":   model_exists,
        "trained_at":     meta.get("trained_at"),
        "auc":            metrics.get("auc"),
        "accuracy":       metrics.get("accuracy"),
        "log_loss":       metrics.get("log_loss"),
        "feature_count":  meta.get("n_features"),
        "feature_cols":   meta.get("feature_cols", []),
        "n_train":        meta.get("n_train"),
        "n_test":         meta.get("n_test"),
        "data_source":    "mock",
        "artifact_path":  "ml/models/risk_model.pkl",
        "meta_available": True,
        "calibration": {
            "rested_score": calibration.get("cal_target_rested"),
            "b2b_score":    calibration.get("cal_target_b2b"),
            "thresholds":   thresholds,
        },
    }
