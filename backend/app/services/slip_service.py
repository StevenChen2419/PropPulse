"""Resolve saved selections without substituting sportsbook, line, or side."""
from app.services.offer_service import valid_odds, offer_availability, decimal_price, utc


def slip_selection(item, prop, now=None):
    sportsbook = getattr(item, "sportsbook", None)
    line = getattr(item, "line", None)
    # Legacy items lack a recorded identity; require explicit reselection.
    current = offer_availability(prop, sportsbook, line, item.side, now)
    original = getattr(item, "original_odds", None)
    original = original if valid_odds(original) else None
    observed = getattr(item, "original_observed_at", None)
    change = None
    if original is not None and current["odds"] is not None:
        delta = decimal_price(current["odds"]) - decimal_price(original)
        change = "improved" if delta > 0 else "worsened" if delta < 0 else "unchanged"
    return {"sportsbook": sportsbook, "line": line, **current,
            "original_odds": original,
            "original_observed_at": utc(observed).isoformat() if observed else None,
            "price_change": change}


def capture_original(item, decision):
    """Only a validated stored offer supplies original evidence; never Prop odds."""
    from datetime import datetime
    item.original_odds = decision["odds"]
    observed = decision["provider_observed_at"]
    item.original_observed_at = utc(datetime.fromisoformat(observed)).replace(tzinfo=None) if observed else None
