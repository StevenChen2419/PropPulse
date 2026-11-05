"""Offline SQL inventory browsing; no application lifespan or provider access."""
from datetime import datetime, timedelta, timezone
import unittest
import os
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.dialects import postgresql

from app.database import Base, get_db
from app.models import Player, Prop, PropBook, Event, PlayerGameLog
from app.routers.props import router, get_discover
from app.services.discover_browse import browse_page
from app.services.offer_service import actionable_offer_filter, eligible_offers, offer_availability


class DiscoverBrowseTests(unittest.TestCase):
    def make_engine(self):
        from sqlalchemy.pool import StaticPool
        return create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)

    def setUp(self):
        self.engine = self.make_engine()
        Base.metadata.create_all(self.engine, tables=[m.__table__ for m in (Player, Prop, PropBook, Event, PlayerGameLog)])
        self.db = Session(self.engine)
        self.now = datetime.now(timezone.utc)
        self.naive = self.now.replace(tzinfo=None)
        self.start = self.naive + timedelta(days=2)
        for index in range(65):
            self.add(f'Player {index:03}', over=100+index)
        self.special = self.add("Connor McDavid", team='Edmonton Oilers', abbr='EDM', over=180)
        self.special.event.scheduled_start_at = self.start + timedelta(days=1)
        self.punctuation = self.add("A.J. O’Neale-Smith", sport='NBA', market='points')
        self.expired = self.add('Expired player', age=7*3600)
        self.unknown = self.add('Unknown observation', age=None)
        self.started = self.add('Started player', start=self.naive-timedelta(seconds=1))
        self.fake = self.add('Synthetic player', provider='mock-event')
        self.future = self.add('Future observation', age=-3600)
        self.offline = self.add('Unsupported book', book='Invented book')
        self.last = self.add('Last known player', age=2*3600)
        self.alternate = self.add('Wrong line player', offer_line=9.5)
        self.no_over = self.add('Under only', over=None, under=140)
        # Multiple books must not multiply rows. A better different line is not
        # an equivalent price, and must not affect this Prop's price ordering.
        self.db.add(PropBook(prop_id=self.special.id, sportsbook='DraftKings', line=9.5,
            over_odds=900, under_odds=-110, provider_observed_at=self.naive))
        self.db.commit()
        app = FastAPI(); app.include_router(router, prefix='/props')
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.engine.dispose); self.addCleanup(self.db.close); self.addCleanup(self.client.close)

    def add(self, name, *, sport='NHL', market='shots_on_goal', team='Away Team', abbr='AWY',
            over=110, under=-110, age=60, book='FanDuel', start=None, provider=None, offer_line=2.5):
        player=Player(name=name, team=team, team_abbr=abbr, sport=sport)
        self.db.add(player); self.db.flush()
        event_row=Event(provider='the_odds_api', provider_event_id=player.id,
            sport_key='icehockey_nhl' if sport=='NHL' else 'basketball_nba',
            home_team='Home Rivals', away_team=team, scheduled_start_at=start or self.start)
        self.db.add(event_row); self.db.flush()
        prop=Prop(player_id=player.id, event_id=event_row.id, prop_type=market, line=2.5,
            sportsbook=book, game_time=self.naive-timedelta(days=1), odds_event_id=provider or player.id,
            opponent='Home Rivals', is_home=False, is_active=True)
        self.db.add(prop); self.db.flush()
        self.db.add(PropBook(prop_id=prop.id, sportsbook=book, line=offer_line, over_odds=over, under_odds=under,
            provider_observed_at=self.naive-timedelta(seconds=age) if age is not None else None,
            ingested_at=self.naive))
        self.db.flush()
        return prop

    def browse(self, **kwargs):
        return browse_page(self.db, limit=24, offset=0, now=self.now, **kwargs)

    def test_full_dataset_search_and_combined_filters_before_pagination(self):
        first, meta=self.browse()
        self.assertEqual(len(first),24)
        self.assertNotIn(self.special.id, [prop.id for prop in first])
        # Search works independently of the first page and absent research logs.
        result=self.client.get('/props/discover',params=dict(browse='true',sport='nhl',prop_type='shots_on_goal',
            sportsbook='fanduel',search='  McDAVID  Edmonton ',limit=1)).json()
        self.assertEqual(result['total'],1)
        self.assertEqual(result['props'][0]['id'],self.special.id)
        self.assertFalse(result['has_more'])
        self.assertEqual(result['props'][0]['player']['id'],self.special.player_id)
        self.assertIn('statistics_coverage',result['props'][0])
        self.assertEqual(self.browse(search='NHL shots-on-goal Home Rivals')[1]['total'],meta['total']-1)
        self.assertEqual(self.browse(sport='NBA',search='McDavid')[1]['total'],0)

    def test_names_teams_punctuation_whitespace_and_empty_search(self):
        self.assertEqual(self.browse(search='A.J.  O\'Neale-Smith')[0][0].id,self.punctuation.id)
        self.assertEqual(self.browse(search='edm')[0][0].id,self.special.id)
        self.assertEqual(self.browse(search=' \t\n')[1]['total'],self.browse()[1]['total'])
        self.assertEqual(self.browse(search="%' OR 1=1 --")[1]['total'],0)

    def test_stable_pages_totals_boundaries_no_duplicate_books(self):
        seen=[]; total=self.browse()[1]['total']
        for offset in range(0,total,7):
            page,meta=browse_page(self.db,limit=7,offset=offset,now=self.now)
            self.assertEqual(meta['total'],total)
            self.assertEqual(meta['has_more'],offset+len(page)<total)
            seen.extend(row.id for row in page)
        self.assertEqual(len(set(seen)),total)
        self.assertEqual(seen,[r.id for offset in range(0,total,7) for r in browse_page(
            self.db,limit=7,offset=offset,now=self.now)[0]])
        page,meta=browse_page(self.db,limit=5,offset=total,now=self.now)
        self.assertEqual(page,[]); self.assertIsNone(meta['next_offset'])

    def test_price_sort_exact_line_null_last_and_directions(self):
        high,_=self.browse(sort='over_desc')
        self.assertEqual(high[0].id,self.special.id) # 180, not alternate line 900
        low,_=self.browse(sort='over_asc')
        self.assertEqual(low[0].player.name,'Player 000')
        all_rows=browse_page(self.db,limit=50,offset=24,sort='over_desc',now=self.now)[0]
        # Last-known rows also have no current actionable sort price. Both
        # null-price rows sort last with the stable Prop ID tie-breaker.
        self.assertEqual([row.id for row in all_rows[-2:]], sorted([self.no_over.id, self.last.id]))
        self.assertEqual(self.browse(sort='under_desc')[0][0].id,self.no_over.id)
        for sort in ('player','market','upcoming','under_asc'):
            self.assertEqual(len(self.browse(sort=sort)[0]),24)

    def test_stale_started_unknown_synthetic_invalid_book_excluded(self):
        rows=browse_page(self.db,limit=50,offset=24,now=self.now)[0]+self.browse()[0]
        ids={row.id for row in rows}
        for prop in (self.expired,self.unknown,self.started,self.fake,self.future,self.offline,self.alternate):
            self.assertNotIn(prop.id,ids)
        for prop in rows:
            self.assertTrue(eligible_offers(prop,self.now))
        rows,meta=self.browse(availability='last_known')
        self.assertEqual([r.id for r in rows],[self.last.id])
        self.assertNotIn(self.last.id,[r.id for r in self.browse(availability='available')[0]])

    def test_sql_offer_policy_matches_authoritative_boundaries_and_missing_sides(self):
        prop=self.special
        offer=next(o for o in prop.book_offers if o.sportsbook=='FanDuel')
        for age in (None,-1,0,1800,1801,21600,21601):
            for over,under in ((None,None),(-99,0),(-110,None),(100,100),(0,120)):
                offer.provider_observed_at=self.naive-timedelta(seconds=age) if age is not None else None
                offer.over_odds=over; offer.under_odds=under; offer.ingested_at=self.naive
                self.db.flush()
                decisions=[offer_availability(prop,'FanDuel',2.5,side,self.now) for side in ('over','under')]
                for availability in (None,'available','last_known'):
                    expected=any(d['availability'] in {'available','last_known'} and (availability is None or d['availability']==availability) for d in decisions)
                    actual=self.db.query(Prop.id).filter(Prop.id==prop.id,Prop.book_offers.any(
                        actionable_offer_filter(self.now,exact_line=True,sportsbook='FanDuel',availability=availability))).first()
                    self.assertEqual(bool(actual),expected,(age,over,under,availability))
                    current=self.db.query(Prop.id).filter(Prop.id==prop.id,Prop.book_offers.any(
                        actionable_offer_filter(self.now,exact_line=True,sportsbook='FanDuel',availability=availability,current_only=True))).first()
                    self.assertEqual(bool(current), any(d['actionable'] for d in decisions))

    def test_dates_use_event_time_and_eastern_bounds(self):
        from zoneinfo import ZoneInfo
        # A future date near the UTC/Eastern boundary, independent of test clock.
        at=self.start.replace(hour=3,minute=30,second=0,microsecond=0)
        day=at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('America/New_York')).date()
        prop=self.add('Date boundary',start=at); self.db.commit()
        rows,_=self.browse(game_date=day.isoformat(),search='Date boundary')
        self.assertEqual([r.id for r in rows],[prop.id])
        self.assertEqual(self.browse(game_date=(day+timedelta(days=1)).isoformat(),search='Date boundary')[1]['total'],0)

    def test_invalid_filters_http_validation_and_empty_results(self):
        for params,status in [({'sport':'not-a-sport'},400),({'sort':'hit_rate'},400),({'limit':51},422),
                ({'limit':0},422),({'offset':-1},422),({'search':'x'*121},422),({'sportsbook':'invented'},400),
                ({'game_date':'2026-02-30'},422),({'game_date':'9999-12-31'},422),
                ({'availability':'expired'},400),({'event_id':'bad'},422)]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get('/props/discover',params={'browse':'true',**params}).status_code,status)
        self.assertEqual(self.browse(prop_type='unsupported_market')[1]['total'],0)
        self.assertEqual(self.browse(sportsbook='DraftKings')[1]['total'],0) # only wrong line

    def test_bounded_queries_and_postgres_parameterized_sql(self):
        self.db.expire_all(); statements=[]
        def capture(conn,cursor,statement,parameters,context,executemany): statements.append(statement)
        event.listen(self.engine,'before_cursor_execute',capture)
        try:
            response=self.client.get('/props/discover',params=dict(browse='true',limit=3))
        finally: event.remove(self.engine,'before_cursor_execute',capture)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()['props']),3)
        self.assertLessEqual(len(statements),6)
        self.assertTrue(any('LIMIT' in sql for sql in statements))
        statement=self.db.query(Prop).filter(Prop.book_offers.any(actionable_offer_filter(self.now,exact_line=True)))
        compiled=statement.statement.compile(dialect=postgresql.dialect())
        self.assertNotIn('FanDuel',str(compiled)); self.assertTrue(compiled.params)

    def test_legacy_discover_call_still_uses_existing_ranked_path(self):
        with patch('app.routers.props.read_prop_inventory',return_value=[]), \
                patch('app.services.discover_browse.browse_page',side_effect=AssertionError('Not a browse request')):
            response=get_discover(db=self.db,limit=20)
        self.assertEqual(response['props'],[])
        self.assertNotIn('filter_options',response)


@unittest.skipUnless(os.environ.get('PROPPULSE_TEST_POSTGRES_URL'), 'Explicit disposable PostgreSQL URL unset')
class DiscoverBrowsePostgresTests(DiscoverBrowseTests):
    # Reuse the existing prefix validation, isolated schemas and bounded cleanup.
    import test_ingestion_postgres as fixture
    setUpClass = classmethod(fixture.IngestionPostgresTests.setUpClass.__func__)
    remove_schema = fixture.IngestionPostgresTests.remove_schema

    def make_engine(self):
        self.fixture.IngestionPostgresTests.setUp(self)
        return self.engine


if __name__=='__main__': unittest.main()
