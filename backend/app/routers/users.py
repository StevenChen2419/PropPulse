from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models import User, SavedProp, Slip, SlipItem, Prop, Player
from app.schemas import (
    UserCreate, UserLogin, AuthResponse,
    UserPreferences, UserOut, PropOut, SlipOut, SlipItemOut, SlipEstimateCreate, ExactSelectionCreate
)
from app.auth import hash_password, verify_password, create_token, get_current_user
from app.services.session_security import issue_csrf, require_csrf, set_session, clear_session
from app.services.fatigue_service import fatigue_to_dict
from app.models import FatigueScore
from app.services.slip_service import slip_selection, capture_original
from app.services.offer_service import offer_availability
from app.routers.props import load_game_logs

router = APIRouter()
user_router = APIRouter()
# Pay the same bcrypt verification cost for unknown email addresses.
_DUMMY_PASSWORD_HASH = hash_password("isolated-dummy-login-value")


@user_router.post("/me/slip/estimate")
def estimate_slip(body: SlipEstimateCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.parlay_service import estimate_parlay
    return estimate_parlay(db, body.items, body.assumed_correlation)

@router.get("/csrf")
def csrf(request: Request, response: Response):
    return issue_csrf(request, response)


@router.post("/register", response_model=AuthResponse, dependencies=[Depends(require_csrf)])
def register(body: UserCreate, db: Session = Depends(get_db), response: Response = None):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(400, "Unable to register account")
    user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent registration may pass the earlier email lookup. Do not
        # expose driver diagnostics (which can contain the submitted email).
        db.rollback()
        raise HTTPException(400, "Unable to register account") from None
    db.refresh(user)
    set_session(response, create_token(user.id))
    return {"ok": True}

@router.post("/login", response_model=AuthResponse, dependencies=[Depends(require_csrf)])
def login(body: UserLogin, db: Session = Depends(get_db), response: Response = None):
    user = db.query(User).filter(User.email == body.email).first()
    valid = verify_password(body.password, user.hashed_password if user else _DUMMY_PASSWORD_HASH)
    if not user or not valid:
        raise HTTPException(401, "Invalid credentials")
    set_session(response, create_token(user.id))
    return {"ok": True}


@router.post("/logout", response_model=AuthResponse, dependencies=[Depends(require_csrf)])
def logout(response: Response):
    clear_session(response)
    return {"ok": True}

@user_router.get("/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)):
    return user

@user_router.put("/me/preferences")
def update_preferences(
    body: UserPreferences,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.fav_sports is not None:
        user.fav_sports = body.fav_sports
    if body.fav_players is not None:
        user.fav_players = body.fav_players
    if body.fav_prop_types is not None:
        user.fav_prop_types = body.fav_prop_types
    db.commit()
    return {"ok": True}

@user_router.get("/me/saved")
def get_saved(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    saved = db.query(SavedProp).filter(SavedProp.user_id == user.id).all()
    props, fatigue = _selection_subjects(db, [row.prop_id for row in saved])
    logs = load_game_logs(db, list(props.values()))
    result, selections = [], []
    for s in saved:
        prop = props.get(s.prop_id)
        if prop:
            output = _prop_out(prop, fatigue.get(prop.player_id), logs)
            if s.side is None:
                result.append(output)
            else:
                selections.append({"id": s.id, "prop_id": s.prop_id, "side": s.side,
                    "saved_at": s.saved_at, "selection": slip_selection(s, prop), "prop": output})
    return {"saved": result, "selections": selections}


def _validated_selection(db, prop_id, body, *, live=False):
    prop = db.query(Prop).filter(Prop.id == prop_id).first()
    if not prop:
        raise HTTPException(404, "Prop not found")
    decision = offer_availability(prop, body.sportsbook, body.line, body.side)
    if decision["odds"] is None or (live and not decision["actionable"]):
        raise HTTPException(409, "This exact offer is unavailable. Your original selection has been kept.")
    return prop, decision


def _commit_selection(db):
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


@user_router.post("/me/saved/selections/{prop_id}")
def save_selection(prop_id: str, body: ExactSelectionCreate,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(User).filter(User.id == user.id).with_for_update().first()
    # Repeated saves keep the original evidence, even after the offer disappears.
    row = db.query(SavedProp).filter(SavedProp.user_id == user.id, SavedProp.prop_id == prop_id,
        SavedProp.sportsbook == body.sportsbook, SavedProp.line == body.line, SavedProp.side == body.side).first()
    if row:
        return {"id": row.id}
    _, decision = _validated_selection(db, prop_id, body)
    row = SavedProp(user_id=user.id, prop_id=prop_id, **body.model_dump())
    capture_original(row, decision)
    db.add(row)
    db.flush()
    result = {"id": row.id}
    _commit_selection(db)
    return result


@user_router.patch("/me/saved/selections/{selection_id}")
def edit_saved_selection(selection_id: str, body: ExactSelectionCreate,
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(User).filter(User.id == user.id).with_for_update().first()
    row = db.query(SavedProp).filter(SavedProp.id == selection_id, SavedProp.user_id == user.id,
                                     SavedProp.side.is_not(None)).first()
    if not row:
        raise HTTPException(404, "Saved selection not found")
    duplicate = db.query(SavedProp).filter(SavedProp.user_id == user.id, SavedProp.prop_id == row.prop_id,
        SavedProp.sportsbook == body.sportsbook, SavedProp.line == body.line, SavedProp.side == body.side).first()
    if duplicate and duplicate.id != row.id:
        raise HTTPException(409, "This exact selection is already saved")
    _, decision = _validated_selection(db, row.prop_id, body)
    if (row.sportsbook, row.line, row.side) != (body.sportsbook, body.line, body.side):
        for key, value in body.model_dump().items():
            setattr(row, key, value)
        capture_original(row, decision)
    _commit_selection(db)
    return {"id": row.id}


@user_router.delete("/me/saved/selections/{selection_id}")
def delete_saved_selection(selection_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(User).filter(User.id == user.id).with_for_update().first()
    row = db.query(SavedProp).filter(SavedProp.id == selection_id, SavedProp.user_id == user.id,
                                     SavedProp.side.is_not(None)).first()
    if not row:
        raise HTTPException(404, "Saved selection not found")
    db.delete(row)
    _commit_selection(db)
    return {"ok": True}


@user_router.patch("/me/slip/items/{prop_id}")
def edit_slip_selection(prop_id: str, body: ExactSelectionCreate,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(User).filter(User.id == user.id).with_for_update().first()
    slip = db.query(Slip).filter(Slip.user_id == user.id, Slip.status == "open").first()
    row = db.query(SlipItem).filter(SlipItem.slip_id == slip.id, SlipItem.prop_id == prop_id).first() if slip else None
    if not row:
        raise HTTPException(404, "Slip selection not found")
    prop, decision = _validated_selection(db, prop_id, body, live=True)
    if (row.sportsbook, row.line, row.side) != (body.sportsbook, body.line, body.side):
        for key, value in body.model_dump().items():
            setattr(row, key, value)
        capture_original(row, decision)
    result = {"id": row.id, "selection": slip_selection(row, prop)}
    _commit_selection(db)
    return result


@user_router.post("/me/saved/selections/{selection_id}/slip")
def saved_selection_to_slip(selection_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(User).filter(User.id == user.id).with_for_update().first()
    saved = db.query(SavedProp).filter(SavedProp.id == selection_id, SavedProp.user_id == user.id,
                                      SavedProp.side.is_not(None)).first()
    if not saved:
        raise HTTPException(404, "Saved selection not found")
    slip = db.query(Slip).filter(Slip.user_id == user.id, Slip.status == "open").first()
    if not slip:
        slip = Slip(user_id=user.id, status="open")
        db.add(slip)
        db.flush()
    item = db.query(SlipItem).filter(SlipItem.slip_id == slip.id, SlipItem.prop_id == saved.prop_id).first()
    if item and (item.sportsbook, item.line, item.side) != (saved.sportsbook, saved.line, saved.side):
        raise HTTPException(409, "This prop already has a different slip selection. Edit it in your slip.")
    if not item:
        item = SlipItem(slip_id=slip.id, prop_id=saved.prop_id, sportsbook=saved.sportsbook,
                        line=saved.line, side=saved.side, original_odds=saved.original_odds,
                        original_observed_at=saved.original_observed_at)
        db.add(item)
    prop = db.query(Prop).filter(Prop.id == saved.prop_id).first()
    result = {"selection": slip_selection(item, prop)}
    _commit_selection(db)
    return result

@user_router.get("/me/slip")
def get_slip(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    slip = db.query(Slip).filter(Slip.user_id == user.id, Slip.status == "open").first()
    if not slip:
        return {"slip": None}
    items = db.query(SlipItem).filter(SlipItem.slip_id == slip.id).all()
    props, fatigue = _selection_subjects(db, [item.prop_id for item in items])
    logs = load_game_logs(db, list(props.values()))
    item_out = []
    for item in items:
        prop = props.get(item.prop_id)
        fs = fatigue.get(prop.player_id) if prop else None
        item_out.append({
            "id": item.id,
            "prop_id": item.prop_id,
            "side": item.side,
            "selection": slip_selection(item, prop),
            "prop": _prop_out(prop, fs, logs) if prop else None,
        })
    return {"slip": {"id": slip.id, "status": slip.status, "items": item_out}}


def _selection_subjects(db, prop_ids):
    """Load only the subjects of the already ownership-filtered selections.

    Keep response order in the caller's saved/item rows. No offer eligibility
    filter belongs here: unavailable historical selections must remain visible.
    """
    if not prop_ids:
        return {}, {}
    props = db.query(Prop).join(Player).options(
        joinedload(Prop.player), joinedload(Prop.event), selectinload(Prop.book_offers),
    ).filter(Prop.id.in_(set(prop_ids))).all()
    player_ids = {prop.player_id for prop in props}
    fatigue = db.query(FatigueScore).filter(FatigueScore.player_id.in_(player_ids)).all() if player_ids else []
    return {prop.id: prop for prop in props}, {score.player_id: score for score in fatigue}

def _prop_out(prop, fs, logs=None):
    from app.routers.props import serialize_prop
    return serialize_prop(prop, logs or {}, fatigue=fatigue_to_dict(fs),
                          line_movement=round(prop.line - (prop.line_24h_ago or prop.line), 2))
