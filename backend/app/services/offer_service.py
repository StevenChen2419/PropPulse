"""Authoritative current-offer policy. Legacy Prop prices are never offers.

Provider market observations alone establish freshness. Missing observations
(including legacy rows) are unavailable until observed. Naive DB times mean UTC.
"""
import math
from datetime import datetime, timedelta, timezone

from app.models import PropBook
from app.services.game_identity_service import game_start

LIVE_WINDOW = timedelta(minutes=30)
OFFER_TTL = timedelta(hours=6)
# Provider bookmaker titles accepted by the current US research application.
SPORTSBOOKS = frozenset(name.casefold() for name in (
    "FanDuel", "DraftKings", "BetMGM", "Caesars", "William Hill (US)",
    "BetRivers", "Bovada", "BetOnline.ag", "BetUS", "MyBookie.ag",
    "LowVig.ag", "SuperBook", "PointsBet (US)", "ESPN BET", "Fanatics",
    "Fanatics Sportsbook", "Hard Rock Bet", "Hard Rock Bet (FL)",
    "Bally Bet", "Circa Sports", "Fliff", "WynnBET", "Unibet",
))


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid_odds(value):
    return valid_number(value) and abs(value) >= 100


def find_offer(prop, sportsbook, line):
    if prop is None or not valid_number(line):
        return None
    return next((offer for offer in prop.book_offers or []
                 if offer.sportsbook == sportsbook and valid_number(offer.line)
                 and offer.line == line), None)


def _offer_context(prop, sportsbook, line, now):
    """Evaluate policy without allocating/formatting response metadata.

    Inventory filtering and scoring need only the state and price. Keep a single
    policy implementation for those callers and the public response serializer.
    """
    offer = find_offer(prop, sportsbook, line)
    observed = getattr(offer, "provider_observed_at", None)
    observed = utc(observed) if observed else None
    age = (now - observed).total_seconds() if observed else None
    def context(blocked=None):
        return offer, observed, age, blocked
    event = getattr(prop, "odds_event_id", None)
    game = game_start(prop)
    if game and utc(game) <= now:
        return context("game_started")
    if (prop is None or not getattr(prop, "is_active", False) or not game
            or not isinstance(event, str) or not event.strip()
            or event.casefold().startswith(("mock", "synthetic", "demo"))
            or not isinstance(sportsbook, str) or sportsbook.casefold() not in SPORTSBOOKS
            or offer is None):
        return context("market_unavailable")
    return context()


def _side_state(context, side):
    offer, observed, age, blocked = context
    def state(availability="market_unavailable", odds=None):
        return offer, observed, age, availability, odds
    if blocked is not None:
        return state(blocked)
    if side not in {"over", "under"}:
        return state()
    if age is not None and age > OFFER_TTL.total_seconds():
        return state("expired")
    odds = getattr(offer, f"{side}_odds", None)
    if age is None or age < 0 or not valid_odds(odds):
        return state()
    return state("last_known" if age > LIVE_WINDOW.total_seconds() else "available", odds)


def _offer_state(prop, sportsbook, line, side, now):
    return _side_state(_offer_context(prop, sportsbook, line, now), side)


def _state_metadata(state, now):
    offer, observed, age, availability, odds = state
    actionable = availability == "available"
    return {"availability": availability, "actionable": actionable,
              "source": "last_known" if availability == "last_known" else "live" if actionable else "unavailable",
              "odds": odds,
              "refreshed_at": observed.isoformat() if observed else None,
              "provider_observed_at": observed.isoformat() if observed else None,
              "ingested_at": utc(offer.ingested_at).isoformat() if getattr(offer, "ingested_at", None) else None,
              "observation_age_seconds": age,
              "expires_at": (observed + OFFER_TTL).isoformat() if observed else None,
              "evaluated_at": now.isoformat()}


def offer_availability(prop, sportsbook, line, side, now=None):
    now = utc(now or datetime.now(timezone.utc))
    return _state_metadata(_offer_state(prop, sportsbook, line, side, now), now)


def available_offer_filter(now=None):
    """Coarse database prefilter; always confirm with the policy above."""
    now = utc(now or datetime.now(timezone.utc)).replace(tzinfo=None)
    return (PropBook.provider_observed_at >= now - OFFER_TTL) & (PropBook.provider_observed_at <= now)


def actionable_offer_filter(now, *, side=None, exact_line=False, sportsbook=None, availability=None, current_only=False):
    """SQL retained-inventory eligibility; current_only restricts live prices.

    Correlates to Prop; use in book_offers.any() or a correlated price subquery.
    Do not use ingestion timestamps or legacy Prop prices for eligibility.
    """
    from sqlalchemy import and_, or_, func
    from app.models import Prop, Event
    from sys import float_info
    cutoff = utc(now).replace(tzinfo=None)
    valid_price = lambda column: or_(column.between(100, float_info.max), column.between(-float_info.max, -100))
    prices = valid_price(getattr(PropBook, f'{side}_odds')) if side else or_(
        valid_price(PropBook.over_odds), valid_price(PropBook.under_odds))
    conditions = [Prop.is_active.is_(True), func.length(func.trim(Prop.odds_event_id)) > 0,
        ~func.lower(Prop.odds_event_id).like('mock%'), ~func.lower(Prop.odds_event_id).like('synthetic%'),
        ~func.lower(Prop.odds_event_id).like('demo%'),
        or_(Prop.event.has(Event.scheduled_start_at > cutoff),
            and_(Prop.event_id.is_(None), Prop.game_time > cutoff)),
        func.lower(PropBook.sportsbook).in_(SPORTSBOOKS), available_offer_filter(now), prices,
        PropBook.line.between(-float_info.max, float_info.max)]
    if exact_line:
        conditions.extend([Prop.line.between(-float_info.max, float_info.max), PropBook.line == Prop.line])
    if sportsbook:
        conditions.append(func.lower(PropBook.sportsbook) == sportsbook.lower())
    if availability == 'available' or current_only:
        conditions.append(PropBook.provider_observed_at >= cutoff - LIVE_WINDOW)
    elif availability == 'last_known':
        conditions.append(PropBook.provider_observed_at < cutoff - LIVE_WINDOW)
    return and_(*conditions)


def eligible_offers(prop, now=None):
    now = utc(now or datetime.now(timezone.utc))
    result = []
    for offer in prop.book_offers or []:
        context = _offer_context(prop, offer.sportsbook, offer.line, now)
        if any(_side_state(context, side)[3] in {"available", "last_known"} for side in ("over", "under")):
            result.append(offer)
    return result


def primary_prices(prop, now=None):
    return {f"{side}_odds": offer_availability(prop, prop.sportsbook, prop.line, side, now)["odds"]
            for side in ("over", "under")}


def primary_offer_status(prop, now=None):
    """Availability of the selected primary book/line; alternatives cannot replace it."""
    now = now or datetime.now(timezone.utc)
    decisions = [offer_availability(prop, prop.sportsbook, prop.line, side, now)
                 for side in ("over", "under")]
    eligible = [decision for decision in decisions if decision["actionable"]]
    chosen = max(eligible, key=lambda decision: decision["observation_age_seconds"], default=None)
    if chosen is None:
        chosen = next((decision for state in ("game_started", "expired", "last_known", "market_unavailable")
                       for decision in decisions if decision["availability"] == state), decisions[0])
    return {key: value for key, value in chosen.items() if key != "odds"}


def _freshness_state(prop, now):
    decisions = []
    for offer in prop.book_offers or []:
        context = _offer_context(prop, offer.sportsbook, offer.line, now)
        decisions.extend(_side_state(context, side) for side in ("over", "under"))
    eligible = [decision for decision in decisions if decision[3] in {"available", "last_known"}]
    # Conservative aggregate: all eligible offers must be fresh to say Live.
    chosen = max(eligible, key=lambda d: d[2], default=None)
    if chosen is None:
        chosen = next((d for d in decisions if d[3] == "game_started"), None)
        chosen = chosen or next((d for d in decisions if d[3] == "expired"), None)
        chosen = chosen or _offer_state(prop, prop.sportsbook, prop.line, "over", now)
    return chosen


def odds_freshness(prop, now=None):
    now = utc(now or datetime.now(timezone.utc))
    return {key: value for key, value in _state_metadata(_freshness_state(prop, now), now).items() if key != "odds"}


def offer_refreshed_at(prop, now=None):
    """The identical conservative observation, without unrelated metadata."""
    observed = _freshness_state(prop, utc(now or datetime.now(timezone.utc)))[1]
    return observed.isoformat() if observed else None


def offer_observation_age(prop, now=None):
    return _freshness_state(prop, utc(now or datetime.now(timezone.utc)))[2]


SPORTSBOOK_DISPLAY_PRIORITY = {"fanduel": 0, "draftkings": 1}

def odds_freshness_for_offer(prop, offer, now=None):
    now = now or datetime.now(timezone.utc)
    decisions = [offer_availability(prop, offer.sportsbook, offer.line, side, now) for side in ("over", "under")]
    decision = next((d for state in ("available", "last_known", "game_started", "expired", "market_unavailable")
                     for d in decisions if d["availability"] == state), decisions[0])
    return {key: value for key, value in decision.items() if key != "odds"}


def decimal_price(odds):
    """Comparable payout, including the equivalent +100 / -100 boundary."""
    return 1 + (odds / 100 if odds > 0 else 100 / -odds)


def comparison_fields(prop, now=None):
    """A Prop owns one Event/Player/market identity. Never merge other Props.

    Each line/direction is an independent comparison; retained prices remain
    visible, but only live offers compete. Ingestion never renews eligibility.
    """
    now = utc(now or datetime.now(timezone.utc))
    groups = {}
    for offer in sorted(prop.book_offers or [], key=lambda o: (o.sportsbook.casefold(), o.sportsbook)):
        if not valid_number(offer.line):
            continue
        context = _offer_context(prop, offer.sportsbook, offer.line, now)
        for side in ("over", "under"):
            decision = _state_metadata(_side_state(context, side), now)
            row = dict(sportsbook=offer.sportsbook, line=offer.line,
                provider_bookmaker_key=getattr(offer, 'provider_bookmaker_key', None),
                provider_title=getattr(offer, 'provider_title', None), **decision)
            groups.setdefault((offer.line, side), []).append(row)
    result = []
    for (line, side), rows in sorted(groups.items()):
        eligible = sorted((r for r in rows if r['actionable']),
                          key=lambda r: (-decimal_price(r['odds']), SPORTSBOOK_DISPLAY_PRIORITY.get(r['sportsbook'].casefold(), 2), r['sportsbook'].casefold(), r['sportsbook']))
        best = eligible[0] if eligible else None
        advantage = ((decimal_price(best['odds']) - decimal_price(eligible[1]['odds'])) * 100
                     if len(eligible) > 1 else None)
        result.append(dict(line=line, side=side, offers=rows, best=best,
                           advantage_per_100=round(advantage, 4) if advantage is not None else None))
    return dict(prop_id=str(getattr(prop, 'id', '')), player_id=str(getattr(prop, 'player_id', '')),
                event_id=str(prop.event_id) if getattr(prop, 'event_id', None) else None,
                market=getattr(prop, 'prop_type', None), groups=result)


def best_line_fields(prop, now=None, *, include_offers=True) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    comparison = comparison_fields(prop, now)
    def best(side):
        group = next((g for g in comparison['groups'] if g['line'] == prop.line and g['side'] == side), None)
        row = group['best'] if group else None
        return {key: row[key] for key in ('sportsbook', 'odds', 'line')} if row else None
    offers = sorted(eligible_offers(prop, now), key=lambda o: (
        SPORTSBOOK_DISPLAY_PRIORITY.get(o.sportsbook.lower(), 2), o.line, o.sportsbook.lower()))
    return {
        'best_over': best('over'), 'best_under': best('under'),
        'sportsbook_count': sum(o.line == prop.line for o in offers),
        'sportsbook_offers': [dict(sportsbook=o.sportsbook, line=o.line,
            provider_bookmaker_key=getattr(o, 'provider_bookmaker_key', None),
            provider_title=getattr(o, 'provider_title', None),
            over_odds=offer_availability(prop, o.sportsbook, o.line, 'over', now)['odds'],
            under_odds=offer_availability(prop, o.sportsbook, o.line, 'under', now)['odds'],
            **odds_freshness_for_offer(prop, o, now)) for o in offers if include_offers],
        **({'comparison': comparison} if include_offers else {}),
    }
