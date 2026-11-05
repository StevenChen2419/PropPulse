from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Prop, Interaction, SavedProp, Slip, SlipItem, User
from app.schemas import InteractionCreate
from app.auth import get_current_user
from app.services.offer_service import find_offer, offer_availability
from app.services.slip_service import capture_original, slip_selection

router = APIRouter()

VALID_ACTIONS = {"like", "dislike", "save", "add_to_slip", "click", "view"}

@router.post("/{prop_id}")
def interact(
    prop_id: str,
    body: InteractionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.action not in VALID_ACTIONS:
        raise HTTPException(400, f"Invalid action. Must be one of: {VALID_ACTIONS}")
    prop = db.query(Prop).filter(Prop.id == prop_id).first()
    if not prop:
        raise HTTPException(404, "Prop not found")

    if body.action == "add_to_slip":
        sportsbook = body.sportsbook if body.sportsbook is not None else prop.sportsbook
        line = body.line if body.line is not None else prop.line
        offer = find_offer(prop, sportsbook, line)
        decision = offer_availability(prop, sportsbook, line, body.side)
        if not decision["actionable"]:
            raise HTTPException(400, f"{body.side.capitalize()} is unavailable for this line and sportsbook")
        # All slip writes lock the same user, including creation of their first slip.
        db.query(User).filter(User.id == user.id).with_for_update().first()

    # Record interaction
    interaction = Interaction(user_id=user.id, prop_id=prop_id, action=body.action)
    db.add(interaction)

    # Bump popularity
    if body.action in ("like", "save", "add_to_slip"):
        prop.popularity_count += 1

    # Handle save
    if body.action == "save":
        existing = db.query(SavedProp).filter(
            SavedProp.user_id == user.id, SavedProp.prop_id == prop_id,
            SavedProp.side.is_(None)
        ).first()
        if not existing:
            db.add(SavedProp(user_id=user.id, prop_id=prop_id))

    # Handle add_to_slip
    if body.action == "add_to_slip":
        slip = db.query(Slip).filter(Slip.user_id == user.id, Slip.status == "open").first()
        if not slip:
            slip = Slip(user_id=user.id, status="open")
            db.add(slip)
            db.flush()
        existing_item = db.query(SlipItem).filter(
            SlipItem.slip_id == slip.id, SlipItem.prop_id == prop_id
        ).first()
        if existing_item:
            changed = (existing_item.side, getattr(existing_item, 'sportsbook', None), getattr(existing_item, 'line', None)) != (body.side, offer.sportsbook, offer.line)
            existing_item.side = body.side
            existing_item.sportsbook = offer.sportsbook
            existing_item.line = offer.line
            if changed:
                capture_original(existing_item, decision)
        else:
            existing_item = SlipItem(slip_id=slip.id, prop_id=prop_id, side=body.side,
                                    sportsbook=offer.sportsbook, line=offer.line)
            capture_original(existing_item, decision)
            db.add(existing_item)

    response = {"ok": True, "action": body.action}
    if body.action == "add_to_slip":
        response["selection"] = slip_selection(existing_item, prop)
    db.commit()
    return response

@router.delete("/{prop_id}/save")
def unsave(
    prop_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(SavedProp).filter(
        SavedProp.user_id == user.id, SavedProp.prop_id == prop_id,
        SavedProp.side.is_(None)
    ).delete()
    db.commit()
    return {"ok": True}

@router.delete("/slip/{prop_id}")
def remove_from_slip(
    prop_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(User).filter(User.id == user.id).with_for_update().first()
    slip = db.query(Slip).filter(Slip.user_id == user.id, Slip.status == "open").first()
    if slip:
        db.query(SlipItem).filter(
            SlipItem.slip_id == slip.id, SlipItem.prop_id == prop_id
        ).delete()
        db.commit()
    return {"ok": True}
