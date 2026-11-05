"""SQL-filtered, bounded browsing on the existing Discover endpoint."""
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, or_, case, func, literal, select
from sqlalchemy.orm import joinedload

from app.models import Event, Player, Prop, PropBook
from app.services.game_identity_service import SPORTS
from app.services.offer_service import actionable_offer_filter, SPORTSBOOKS

SORTS = {'upcoming', 'player', 'market', 'over_desc', 'over_asc', 'under_desc', 'under_asc'}
EASTERN = ZoneInfo('America/New_York')


def normalized_text(value):
    value = value.lower()
    for punctuation in ("'", '’', '.'):
        value = value.replace(punctuation, '')
    return ' '.join(re.findall(r'[^\W_]+', value))


def searchable_text(columns):
    text = literal('')
    for column in columns:
        text = text + literal(' ') + func.coalesce(column, '')
    text = func.lower(text)
    for punctuation in ("'", '’', '.'):
        text = func.replace(text, punctuation, '')
    for punctuation in ('_', '-', '/', '@', ',', ':', '(', ')'):
        text = func.replace(text, punctuation, ' ')
    return text


def browse_page(db, *, limit, offset, sport=None, prop_type=None, search=None, sportsbook=None,
                game_date=None, availability=None, sort='upcoming', context=None, now=None):
    now = now or datetime.now(timezone.utc)
    sport = sport.upper() if sport else None
    if sport and sport not in SPORTS.values():
        raise HTTPException(400, 'Unsupported sport')
    if sort not in SORTS or availability not in (None, '', 'available', 'last_known'):
        raise HTTPException(400, 'Unsupported sort or availability')
    if sportsbook and sportsbook.lower() not in SPORTSBOOKS:
        raise HTTPException(400, 'Unsupported sportsbook')
    if not 1 <= limit <= 50 or not 0 <= offset <= 1000000:
        raise HTTPException(422, 'Invalid pagination')
    if len(search or '') > 120 or len(prop_type or '') > 60 or len(sportsbook or '') > 80:
        raise HTTPException(422, 'Filter too long')
    # Event sport/start are authoritative when linked; legacy props retain their
    # existing identity. Joining offers is intentionally avoided (one row/Prop).
    sport_column = case(SPORTS, value=Event.sport_key, else_=Player.sport)
    start = case((Prop.event_id.is_not(None), Event.scheduled_start_at), else_=Prop.game_time)
    eligible = actionable_offer_filter(now, exact_line=True)
    query = db.query(Prop).join(Player).outerjoin(Event, Prop.event_id == Event.id).filter(
        sport_column.in_(set(SPORTS.values())), Prop.book_offers.any(eligible))
    if sport:
        query = query.filter(sport_column == sport)
    # Facets are actual eligible inventory scoped by sport, not a provider
    # entitlement claim. Independent of other filters so empty views are editable.
    markets = [row[0] for row in query.with_entities(Prop.prop_type).distinct().order_by(Prop.prop_type).all()]
    ids = query.with_entities(Prop.id).subquery()
    books = [row[0] for row in db.query(PropBook.sportsbook).join(Prop, Prop.id == PropBook.prop_id).filter(
        Prop.id.in_(select(ids.c.id)), eligible).distinct().order_by(PropBook.sportsbook).all()]
    if prop_type:
        query = query.filter(Prop.prop_type == prop_type)
    matching = actionable_offer_filter(now, exact_line=True, sportsbook=sportsbook, availability=availability)
    query = query.filter(Prop.book_offers.any(matching))
    if context:
        if context['event_id']:
            query = query.filter(Prop.event_id == context['event_id'])
        else:
            # resolve_game already verifies the legacy namespace is unambiguous.
            team = func.coalesce(func.nullif(Player.team, ''), Player.team_abbr)
            query = query.filter(Prop.event_id.is_(None), start == datetime.fromisoformat(
                context['game_time']).replace(tzinfo=None), sport_column == context['sport'],
                or_(and_(Prop.is_home.is_(True), team == context['home_team'],
                         Prop.opponent == context['away_team']),
                    and_(Prop.is_home.is_(False), team == context['away_team'],
                         Prop.opponent == context['home_team'])))
    if game_date:
        try:
            day = date.fromisoformat(game_date)
            if day.isoformat() != game_date:
                raise ValueError()
            bounds = [datetime.combine(d, time(), EASTERN).astimezone(timezone.utc).replace(tzinfo=None)
                      for d in (day, day + timedelta(days=1))]
        except (ValueError, OverflowError):
            raise HTTPException(422, 'Use YYYY-MM-DD for game_date (Eastern)') from None
        query = query.filter(start >= bounds[0], start < bounds[1])
    text = searchable_text([Player.name, Player.team, Player.team_abbr, sport_column,
                            Prop.prop_type, Prop.opponent, Event.home_team, Event.away_team])
    for token in normalized_text(search or '').split():
        query = query.filter(text.contains(token, autoescape=True))
    total = query.count()
    if sort.startswith(('over_', 'under_')):
        side, direction = sort.split('_')
        # Only valid prices on this Prop's exact line; decimal payout ordering
        # agrees with American price ordering in the supported +/-100 ranges.
        price = select(func.max(getattr(PropBook, f'{side}_odds'))).where(
            PropBook.prop_id == Prop.id, actionable_offer_filter(now, side=side,
                exact_line=True, sportsbook=sportsbook, availability=availability, current_only=True)).correlate(Prop).scalar_subquery()
        ordering = [price.is_(None), price.desc() if direction == 'desc' else price.asc()]
    elif sort == 'player':
        ordering = [func.lower(Player.name), start]
    elif sort == 'market':
        ordering = [Prop.prop_type, Prop.line, start]
    else:
        ordering = [start]
    page = query.order_by(*ordering, Prop.id).offset(offset).limit(limit).options(
        joinedload(Prop.player), joinedload(Prop.event), joinedload(Prop.book_offers)).all()
    return page, dict(total=total, limit=limit, offset=offset, has_more=offset + len(page) < total,
        next_offset=offset + len(page) if offset + len(page) < total else None,
        filter_options=dict(sports=sorted(set(SPORTS.values())), markets=markets, sportsbooks=books))
