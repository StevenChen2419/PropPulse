from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Event, NBAEvidenceRecord, Player, PlayerGameLog, Prop, PropBook, PropBookSnapshot
from app.routers.players import router
from app.services.nba_api_provider import normalize_player_statistics
from app.services.nba_season_summary import build_nba_season_summary
from nba_statistics_fixture import PLAYER_ID, seed_statistics, statistics_fixture
import test_event_migration_postgres as pg_fixture

NOW = datetime(2026, 10, 18, 18, tzinfo=timezone.utc)


class SeasonSummaryTests(unittest.TestCase):
    def setUp(self):
        payload, crosswalk, season, observed = statistics_fixture(NOW)
        self.logs = [SimpleNamespace(**row) for row in normalize_player_statistics(payload,
            observed_at=observed, crosswalk=crosswalk, season=season, competition="Regular Season")]
        self.player = SimpleNamespace(id=PLAYER_ID, sport="NBA")

    def summary(self, **kwargs):
        return build_nba_season_summary(self.player, self.logs, now=NOW, **kwargs)

    def test_windows_select_appearances_before_independent_denominators(self):
        result = self.summary()
        self.assertEqual(result["source"], "nba_com_stats")
        self.assertEqual(result["recorded_appearances"], 12)
        self.assertEqual(result["l5"]["appearances"], 5)
        self.assertEqual(result["l5"]["points"], {"average": 4, "valid_samples": 4})
        self.assertEqual(result["l5"]["rebounds"], {"average": 1.75, "valid_samples": 4})
        self.assertEqual(result["l5"]["assists"], {"average": 2.8, "valid_samples": 5})
        self.assertEqual(result["l5"]["minutes"], {"average": 32.25, "valid_samples": 4})
        self.assertEqual(result["l10"]["points"], {"average": 9.56, "valid_samples": 9})
        self.assertEqual(result["l10"]["minutes"], {"average": 34.89, "valid_samples": 9})
        self.assertEqual(result["calendar_day_gap"], 3)
        self.assertEqual(result["full_intervening_days"], 2)
        self.assertEqual(result["date_precision"], "eastern_date")

    def test_scope_duplicate_and_no_espn_fill(self):
        self.logs = self.logs[:2] + self.logs[:1]
        self.logs.append(SimpleNamespace(player_id=PLAYER_ID, sport="NBA", source="espn_nba",
            external_game_id="espn:fixture", game_date=datetime(2026,10,14,12), stats={"points": 99, "minutes": 30}))
        result = self.summary()
        self.assertEqual(result["l10"]["appearances"], 2)
        self.assertEqual(result["l10"]["points"]["average"], 1)
        self.assertEqual(self.summary(season="2025-26")["status"], "unavailable")
        self.assertEqual(self.summary(competition="Playoffs")["status"], "unavailable")
        self.assertIsNone(self.summary(competition="Playoffs")["source"])

    def test_current_season_never_substitutes_historical_or_unscoped_espn(self):
        for row in self.logs:
            row.stats['_nba']['season'] = '2025-26'
        self.logs.append(SimpleNamespace(player_id=PLAYER_ID, sport='NBA', source='espn_nba',
            external_game_id='espn:unclassified', game_date=datetime(2026, 10, 14, 12),
            stats={'points': 99, 'minutes': 30}))
        result = self.summary()
        self.assertEqual(result['season'], '2026-27')
        self.assertEqual(result['competition'], 'Regular Season')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['l5']['points'], {'average': None, 'valid_samples': 0})
        self.assertEqual(result['l10']['appearances'], 0)
        self.assertTrue(any('not substituted' in note for note in result['notes']))

    def test_old_event_reference_does_not_change_default_season(self):
        result = self.summary(reference=datetime(2026, 4, 1, tzinfo=timezone.utc))
        self.assertEqual(result['season'], '2026-27')
        self.assertEqual(result['status'], 'unavailable')

    def test_two_completed_current_games_use_two_valid_samples(self):
        now = datetime(2026, 10, 24, 18, tzinfo=timezone.utc)
        self.logs = self.logs[:2]
        for index, row in enumerate(self.logs):
            row.game_date = datetime(2026, 10, 21 + index, 4)
            row.stats['_nba']['game_date'] = f'2026-10-{21 + index}'
            row.stats['_nba']['observed_at'] = '2026-10-24T12:00:00+00:00'
            row.stats.update(points=20 + index * 10, minutes=30)
        result = build_nba_season_summary(self.player, self.logs, now=now)
        for window in ('l5', 'l10'):
            self.assertEqual(result[window]['appearances'], 2)
            self.assertEqual(result[window]['points'], {'average': 25, 'valid_samples': 2})
        self.assertEqual(result['latest_appearance'], '2026-10-22')

    def test_threes_have_independent_partial_samples_without_season_mixing(self):
        self.logs=self.logs[:2]
        self.logs[0].stats['threes']=0
        self.logs[1].stats['threes']=None
        result=self.summary()
        self.assertEqual(result['l5']['threes'],dict(average=0,valid_samples=1))
        self.assertEqual(result['l10']['appearances'],2)
        self.assertIn(dict(key='threes',label='3PM'),result['metrics'])
        self.assertEqual(self.summary(season='2025-26')['l5']['threes'],dict(average=None,valid_samples=0))

    def test_observation_after_reference_is_withheld_without_fallback(self):
        result = self.summary(reference=NOW-timedelta(days=1))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["source"], "nba_com_stats")

    def test_future_reference_and_small_sample(self):
        self.logs = self.logs[:1]
        result = self.summary(reference=NOW+timedelta(days=2))
        self.assertEqual(result["calendar_day_gap"], 5)
        self.assertEqual(result["l10"]["appearances"], 1)
        self.assertTrue(any("intervening" in note for note in result["notes"]))

    def test_accepted_scope_without_appearances_never_fills_from_espn(self):
        self.logs = self.logs[:1]
        self.logs[0].stats["_nba"]["appearance"] = False
        self.logs.append(SimpleNamespace(player_id=PLAYER_ID, sport="NBA", source="espn_nba",
            external_game_id="espn:fixture", game_date=datetime(2026,10,14,12), stats={"points": 99, "minutes": 30}))
        result = self.summary()
        self.assertEqual(result["source"], "nba_com_stats")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["l5"]["appearances"], 0)


class SeasonResearchAPITests(unittest.TestCase):
    def test_empty_current_historical_partial_and_retained_expired_prop(self):
        engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine, tables=[model.__table__ for model in
            (Player, Event, Prop, PropBook, PropBookSnapshot, PlayerGameLog, NBAEvidenceRecord)])
        with Session(engine) as db:
            player = Player(id=PLAYER_ID, name='Invented season research player', sport='NBA', team='Unknown', team_abbr='UNK')
            db.add(player)
            db.add(Event(id='6b000000-0000-4000-8000-000000000002', provider='fixture',
                provider_event_id='fixture', sport_key='basketball_nba', home_team='Boston Celtics',
                away_team='Orlando Magic', scheduled_start_at=datetime(2026, 10, 25, 23)))
            db.flush()
            prop = Prop(id='6b000000-0000-4000-8000-000000000003', player_id=PLAYER_ID,
                event_id='6b000000-0000-4000-8000-000000000002', prop_type='points', line=20.5,
                sportsbook='Unavailable fixture', is_active=False)
            db.add(prop)
            # Historical NBA.com fixture passes through the real normalizer.
            from test_nba_statistics_import import payload
            from app.services.nba_api_provider import verified_crosswalk
            crosswalk = verified_crosswalk([dict(player_id=PLAYER_ID, nba_player_id='1627759',
                verified=True, provenance='Invented offline identity fixture')])
            records = normalize_player_statistics(payload(), observed_at=datetime(2026, 1, 20, tzinfo=timezone.utc),
                crosswalk=crosswalk, season='2025-26', competition='Regular Season')
            db.add_all(PlayerGameLog(**record) for record in records)
            db.commit()
            app = FastAPI()
            app.include_router(router, prefix='/players')
            app.dependency_overrides[get_db] = lambda: db
            with patch('requests.sessions.Session.request', side_effect=AssertionError('No HTTP')), TestClient(app) as client:
                path = f'/players/{PLAYER_ID}/research'
                empty = client.get(path).json()
                self.assertEqual(empty['season_summary']['season'], '2026-27')
                self.assertEqual(empty['season_summary']['status'], 'unavailable')
                historical = client.get(path, params={'season': '2025-26', 'prop_id': prop.id}).json()
                self.assertEqual(historical['season_summary']['l5']['appearances'], 1)
                self.assertEqual(historical['season_summary']['source'], 'nba_com_stats')
                self.assertEqual(historical['selected_prop']['id'], prop.id)
                self.assertEqual(historical['selected_prop']['event_id'], prop.event_id)
                self.assertFalse(historical['selection_available'])
                self.assertIsNone(historical['selected_prop']['over_odds'])
                # Mock future evaluation after two completed games, never provider HTTP.
                future = datetime(2026, 10, 24, 18, tzinfo=timezone.utc)
                table = payload()['resultSets'][0]
                for index in range(2):
                    row = dict(zip(table['headers'], table['rowSet'][0]))
                    row.update(Game_ID=f'002260000{index+1}', SEASON_ID='22026',
                        GAME_DATE=f'OCT {21+index}, 2026', PTS=20+index*10)
                    normalized = normalize_player_statistics(payload(row), observed_at=future,
                        crosswalk=crosswalk, season='2026-27', competition='Regular Season')
                    db.add_all(PlayerGameLog(**record) for record in normalized)
                db.commit()
                with patch('app.routers.players.build_sport_summary', side_effect=lambda *a, **kw:
                        build_nba_season_summary(*a, **kw, now=future)):
                    partial = client.get(path, params={'prop_id': prop.id}).json()
                self.assertEqual(partial['season_summary']['l5']['points'], {'average': 25, 'valid_samples': 2})
                self.assertEqual(partial['season_summary']['l10']['appearances'], 2)
                self.assertFalse(partial['selection_available'])


@unittest.skipUnless(pg_fixture.TEST_URL, "Explicit disposable PostgreSQL URL unset")
class SeasonSummaryPostgresTests(unittest.TestCase):
    setUpClass = classmethod(pg_fixture.EventMigrationPostgresTests.setUpClass.__func__)
    remove_schema = pg_fixture.EventMigrationPostgresTests.remove_schema
    upgrade = pg_fixture.EventMigrationPostgresTests.upgrade

    def setUp(self):
        pg_fixture.EventMigrationPostgresTests.setUp(self)
        self.upgrade("20261018_04")
        with Session(self.engine) as db, db.begin():
            seed_statistics(db, datetime.now(timezone.utc))
            db.add(Event(id="5b000000-0000-4000-8000-000000000002", provider="fixture_5b",
                sport_key="basketball_nba", provider_event_id="fixture-statistics", home_team="Boston Celtics",
                away_team="Orlando Magic", scheduled_start_at=datetime.now(timezone.utc)+timedelta(days=2)))
            db.flush()
            db.add(Prop(id="5b000000-0000-4000-8000-000000000003", player_id=PLAYER_ID,
                event_id="5b000000-0000-4000-8000-000000000002", prop_type="points", line=20.5,
                sportsbook="Fixture unavailable", is_active=False))

    def test_player_only_and_exact_selection_are_read_only(self):
        statements = []
        @event.listens_for(self.engine, "before_cursor_execute")
        def record(_conn, _cursor, statement, *_args):
            statements.append(statement)
        app = FastAPI()
        app.include_router(router, prefix="/players")
        def database():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = database
        with patch("requests.sessions.Session.request", side_effect=AssertionError("No provider HTTP")), TestClient(app) as client:
            result = client.get(f"/players/{PLAYER_ID}/research").json()
            self.assertIsNone(result["selected_prop"])
            self.assertEqual(result["season_summary"]["l5"]["points"]["average"], 4)
            result = client.get(f"/players/{PLAYER_ID}/research?prop_id=5b000000-0000-4000-8000-000000000003").json()
            self.assertEqual(result["selected_prop"]["id"], "5b000000-0000-4000-8000-000000000003")
            self.assertEqual(result["selected_prop"]["event_id"], "5b000000-0000-4000-8000-000000000002")
            self.assertEqual(result["season_summary"]["calendar_day_gap"], 5)
            self.assertEqual(client.get(f"/players/{PLAYER_ID}/research?season=2025-27").status_code, 422)
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement in statements))
