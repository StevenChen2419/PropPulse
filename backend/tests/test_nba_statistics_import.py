"""NBA statistics fixtures only; no provider transport or application lifespan."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import unittest

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Player, PlayerGameLog
from app.services.nba_api_provider import normalize_player_statistics, verified_crosswalk
from app.services.nba_statistics_service import import_player_statistics
from app.services.nba_season_summary import build_nba_season_summary
import test_event_migration_postgres as pg_fixture


OBSERVED = datetime(2026, 1, 20, 12, tzinfo=timezone.utc)


def payload(*rows):
    rows = rows or [dict(Player_ID=1627759, Game_ID="0022500001", SEASON_ID="22025",
        GAME_DATE="JAN 15, 2026", MATCHUP="BOS vs. ORL", WL='W', MIN=30, PTS=0, REB=4, AST=5)]
    headers = list(rows[0])
    return {"resultSets": [dict(name="PlayerGameLog", headers=headers,
        rowSet=[[row.get(key) for key in headers] for row in rows])]}


class StatisticsNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.player_id = str(uuid4())
        self.crosswalk = verified_crosswalk([dict(nba_player_id="1627759", player_id=self.player_id,
            verified=True, provenance="Explicit synthetic fixture identity review")])

    def normalize(self, data=None, **kwargs):
        return normalize_player_statistics(data or payload(), observed_at=OBSERVED,
            crosswalk=self.crosswalk, season="2025-26", competition="Regular Season", **kwargs)

    def mutate(self, **values):
        data = payload()
        table = data["resultSets"][0]
        for key, value in values.items():
            table["rowSet"][0][table["headers"].index(key)] = value
        return data

    def test_identity_precision_zero_and_metadata(self):
        row = self.normalize()[0]
        self.assertEqual(row["external_game_id"], "nba_com:0022500001")
        self.assertEqual(row["player_id"], self.player_id)
        self.assertEqual(row["game_date"], datetime(2026, 1, 15, 5))
        self.assertEqual(row["stats"]["points"], 0)
        self.assertEqual(row["stats"]["pra"], 9)
        meta = row["stats"]["_nba"]
        self.assertEqual(meta["date_precision"], "eastern_date")
        self.assertEqual(meta["observed_at"], OBSERVED.isoformat())
        self.assertTrue(meta["appearance"])
        self.assertNotIn("completed_at", meta)

    def test_current_regular_season_finality_identity_date_and_threes(self):
        observed = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        row = dict(Player_ID=1627759, Game_ID='0022600001', SEASON_ID='22026',
            GAME_DATE='OCT 20, 2026', MATCHUP='BOS vs. ORL', WL='W', MIN='32:30', PTS=20, REB=4, AST=5, FG3M=3)
        def current(values):
            return normalize_player_statistics(payload(values), observed_at=observed, crosswalk=self.crosswalk,
                season='2026-27', competition='Regular Season')
        record = current(row)[0]
        self.assertEqual(record['external_game_id'], 'nba_com:0022600001')
        self.assertEqual(record['game_date'], datetime(2026,10,20,4))
        self.assertEqual(record['stats']['threes'], 3)
        self.assertEqual(record['stats']['minutes'], 32.5)
        for changes in (dict(WL=None),dict(WL=''),dict(Game_ID='0012600001'),dict(Game_ID='0042600001'),
                        dict(SEASON_ID='22025'),dict(Player_ID=2544),dict(GAME_DATE='OCT 21, 2026')):
            with self.subTest(changes=changes),self.assertRaises(ValueError): current(row | changes)
        missing=dict(row);del missing['WL']
        with self.assertRaises(ValueError): current(missing)

    def test_current_import_replay_preserves_historical_games_in_sqlite(self):
        from sqlalchemy import create_engine
        from app.database import Base
        engine=create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine,tables=[Player.__table__,PlayerGameLog.__table__])
        historical=dict(observed_at=OBSERVED,crosswalk=self.crosswalk,season='2025-26',competition='Regular Season')
        current=dict(historical,observed_at=datetime(2026,10,21,12,tzinfo=timezone.utc),season='2026-27')
        data=payload(dict(Player_ID=1627759,Game_ID='0022600001',SEASON_ID='22026',GAME_DATE='OCT 20, 2026',
            MATCHUP='BOS vs. ORL',WL='L',MIN=20,PTS=10,REB=2,AST=1,FG3M=None))
        with Session(engine) as db,db.begin():
            db.add(Player(id=self.player_id,name='Invented current-season player',sport='NBA',team='Boston',team_abbr='BOS'))
            db.flush()
            self.assertEqual(import_player_statistics(db,payload(),**historical)['inserted'],1)
            old=db.scalar(select(PlayerGameLog).where(PlayerGameLog.external_game_id=='nba_com:0022500001'))
            before=deepcopy(old.stats)
            self.assertEqual(import_player_statistics(db,data,**current)['inserted'],1)
            self.assertEqual(import_player_statistics(db,data,**current)['unchanged'],1)
            self.assertEqual(db.query(PlayerGameLog).count(),2)
            self.assertEqual(old.stats,before)

    def test_missing_malformed_and_minutes_never_become_zero(self):
        for value in [None, "bad", -1, float("nan"), True, 101]:
            row = self.normalize(self.mutate(MIN=value, PTS=None, REB="bad", AST=False))[0]
            self.assertIsNone(row["stats"]["minutes"])
            self.assertIsNone(row["stats"]["points"])
            self.assertIsNone(row["stats"]["rebounds"])
            self.assertIsNone(row["stats"]["assists"])
            self.assertFalse(row["stats"]["_nba"]["appearance"])
        row = self.normalize(self.mutate(MIN=0, PTS=0, REB=0, AST=0))[0]
        self.assertEqual(row["stats"]["minutes"], 0)
        self.assertFalse(row["stats"]["_nba"]["appearance"])
        self.assertEqual(self.normalize(self.mutate(MIN="30:30"))[0]["stats"]["minutes"], 30.5)

    def test_duplicate_games_deduplicate_or_reject_conflict(self):
        data = payload()
        table = data["resultSets"][0]
        table["rowSet"].append(deepcopy(table["rowSet"][0]))
        self.assertEqual(len(self.normalize(data)), 1)
        table["rowSet"][1][table["headers"].index("PTS")] = 3
        with self.assertRaises(ValueError):
            self.normalize(data)

    def test_positive_counts_establish_appearance_with_missing_or_zero_minutes(self):
        for minutes in (None, 0):
            for statistic in ("PTS", "REB", "AST"):
                with self.subTest(minutes=minutes, statistic=statistic):
                    values = dict(MIN=minutes, PTS=0, REB=0, AST=0)
                    values[statistic] = 1
                    row = self.normalize(self.mutate(**values))[0]
                    self.assertTrue(row["stats"]["_nba"]["appearance"])
                    self.assertEqual(row["stats"]["minutes"], minutes)
                    summary = build_nba_season_summary(SimpleNamespace(id=self.player_id, sport="NBA"),
                        [SimpleNamespace(**row)], now=OBSERVED, season="2025-26")
                    self.assertEqual(summary["l5"]["appearances"], 1)
                    self.assertEqual(summary["l5"]["minutes"]["valid_samples"], int(minutes is not None))
                    for key in ("points", "rebounds", "assists"):
                        self.assertEqual(summary["l5"][key]["valid_samples"], 1)

    def test_season_dates_cannot_precede_the_explicit_season(self):
        for day in ("JAN 15, 2025", "SEP 30, 2025"):
            with self.subTest(day=day), self.assertRaises(ValueError):
                self.normalize(self.mutate(GAME_DATE=day))
        self.assertEqual(self.normalize(self.mutate(GAME_DATE="OCT 01, 2025"))[0]["stats"]["_nba"]["season"], "2025-26")
        # Synthetic postponed-season shape: explicit IDs, not month rollover,
        # keep a late finish in its original season.
        late = self.mutate(Game_ID="0041900001", SEASON_ID="42019", GAME_DATE="OCT 11, 2020")
        row = normalize_player_statistics(late, observed_at=OBSERVED, crosswalk=self.crosswalk,
            season="2019-20", competition="Playoffs")[0]
        self.assertEqual(row["stats"]["_nba"]["season"], "2019-20")

    def test_malformed_clock_minutes_never_establish_appearance(self):
        for value in ["-0:30", "1.5:30", "1:60", "1:-2", "1:5", "1:02:03",
                      [30], (30,), {"minutes": 30}, 10 ** 400]:
            with self.subTest(minutes=value):
                row = self.normalize(self.mutate(MIN=value, PTS=0, REB=0, AST=0))[0]
                self.assertIsNone(row["stats"]["minutes"])
                self.assertFalse(row["stats"]["_nba"]["appearance"])
        self.assertEqual(self.normalize(self.mutate(MIN="00:30"))[0]["stats"]["minutes"], 0.5)
        self.assertEqual(self.normalize(self.mutate(MIN="1:30.5"))[0]["stats"]["minutes"], 1 + 30.5 / 60)

    def test_malformed_counting_statistics_remain_null(self):
        for value in [[1], (1,), {"points": 1}, 10 ** 400, 1.5]:
            with self.subTest(points=value):
                row = self.normalize(self.mutate(MIN=None, PTS=value, REB=0, AST=0))[0]
                self.assertIsNone(row["stats"]["points"])
                self.assertFalse(row["stats"]["_nba"]["appearance"])

    def test_identity_scope_and_bounds_fail_closed(self):
        for values in [dict(Player_ID=2544), dict(Game_ID="invalid"),
                       dict(Game_ID="0042500001"), dict(SEASON_ID="22024"),
                       dict(GAME_DATE="JAN 20, 2026"), dict(MATCHUP="BOS vs. BOS")]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.normalize(self.mutate(**values))
        with self.assertRaises(ValueError):
            self.normalize(max_records=0)
        with self.assertRaises(ValueError):
            normalize_player_statistics(payload(), observed_at=OBSERVED,
                crosswalk=dict(self.crosswalk), season="2025-26", competition="Regular Season")

    def test_trade_team_comes_from_game_not_current_player(self):
        row = self.normalize(self.mutate(MATCHUP="LAL @ BOS"))[0]
        self.assertEqual(row["opponent"], "BOS")
        self.assertFalse(row["is_home"])
        self.assertEqual(row["stats"]["_nba"]["team_id"], "1610612747")


@unittest.skipUnless(pg_fixture.TEST_URL, "Explicit disposable PostgreSQL URL unset")
class StatisticsPersistencePostgresTests(unittest.TestCase):
    # Reuse existing disposable schema + migration infrastructure, never app DB.
    setUpClass = classmethod(pg_fixture.EventMigrationPostgresTests.setUpClass.__func__)
    remove_schema = pg_fixture.EventMigrationPostgresTests.remove_schema
    upgrade = pg_fixture.EventMigrationPostgresTests.upgrade

    def setUp(self):
        pg_fixture.EventMigrationPostgresTests.setUp(self)
        self.upgrade("20261018_04")
        self.player_id = str(uuid4())
        self.crosswalk = verified_crosswalk([dict(nba_player_id="1627759", player_id=self.player_id,
            verified=True, provenance="Explicit synthetic fixture identity review")])
        with Session(self.engine) as db, db.begin():
            db.add(Player(id=self.player_id, name="Fixture Brown", team="Boston", team_abbr="BOS", sport="NBA"))

    def import_rows(self, db, data=None):
        return import_player_statistics(db, data or payload(), observed_at=OBSERVED,
            crosswalk=self.crosswalk, season="2025-26", competition="Regular Season")

    def test_statistics_idempotent_and_espn_preserved(self):
        with Session(self.engine) as db, db.begin():
            db.add(PlayerGameLog(player_id=self.player_id, sport="NBA", external_game_id="0022500001",
                source="espn_nba", game_date=datetime(2026, 1, 15), stats={"points": 99}))
        with Session(self.engine) as db, db.begin():
            self.assertEqual(self.import_rows(db)["inserted"], 1)
            self.assertEqual(self.import_rows(db)["unchanged"], 1)
        with Session(self.engine) as db:
            rows = list(db.scalars(select(PlayerGameLog)))
            self.assertEqual(len(rows), 2)
            self.assertEqual(next(r for r in rows if r.source == "espn_nba").stats, {"points": 99})

    def test_failed_import_rolls_back_earlier_writes(self):
        bad = payload()
        table = bad["resultSets"][0]
        second = deepcopy(table["rowSet"][0])
        second[table["headers"].index("Game_ID")] = "0022500002"
        table["rowSet"].append(second)
        with Session(self.engine) as db, db.begin():
            db.add(PlayerGameLog(player_id=self.player_id, sport="NBA", external_game_id="nba_com:0022500002",
                source="espn_nba", game_date=datetime(2026, 1, 15), stats={"points": 99}))
        with Session(self.engine) as db, db.begin():
            with self.assertRaises(ValueError):
                self.import_rows(db, bad)
        with Session(self.engine) as db:
            self.assertEqual(len(list(db.scalars(select(PlayerGameLog)))), 1)

    def test_missing_local_player_rejects_import(self):
        crosswalk = verified_crosswalk([dict(nba_player_id="1627759", player_id=str(uuid4()),
            verified=True, provenance="Wrong synthetic UUID fixture")])
        with Session(self.engine) as db, db.begin(), self.assertRaises(ValueError):
            import_player_statistics(db, payload(), observed_at=OBSERVED,
                crosswalk=crosswalk, season="2025-26", competition="Regular Season")
