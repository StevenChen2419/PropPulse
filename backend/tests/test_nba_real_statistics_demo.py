"""Invented NBA-shaped unit data only; no network or application database."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.database import Base, get_db
from app.models import Event, NBAEvidenceRecord, Player, PlayerGameLog, Prop, PropBook
from app.services.nba_season_summary import build_nba_season_summary
from nba_real_statistics_demo import IDENTITIES, _rows, load_artifact, seed_real_statistics_demo, source_oracle
import test_event_migration_postgres as pg_fixture


def invented_artifact():
    """actual_source exercises validation only; these are invented test numbers."""
    rows = [dict(Player_ID=2544, Game_ID=f"00225000{i:02d}", SEASON_ID="22025", WL='W',
        GAME_DATE=f"APR {20-i:02d}, 2026", MATCHUP="LAL vs. BOS", MIN=30+i,
        PTS=i*2, REB=i, AST=0 if i == 0 else i+1) for i in range(12)]
    rows[1]["MIN"] = None
    rows[2]["PTS"] = None
    return dict(actual_source=True, season="2025-26", competition="Regular Season",
        requests=[dict(endpoint="PlayerGameLog", outcome="invented test fixture; no request executed")],
        players=[dict(nba_player_id="2544", observed_at="2026-10-18T12:00:00+00:00",
            payload={"resultSets": [dict(name="PlayerGameLog", headers=list(rows[0]),
                rowSet=[list(row.values()) for row in rows])]})])


class RealStatisticsDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "invented.json"
        self.data = invented_artifact()
        self.write()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine, tables=[model.__table__ for model in
            (Player, Event, Prop, PlayerGameLog, PropBook)])
        self.addCleanup(self.engine.dispose)

    def write(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def test_raw_oracle_keeps_missing_denominators_and_zeros(self):
        actual = source_oracle(self.data["players"][0]["payload"])
        self.assertEqual(actual["latest_appearance"], "2026-04-20")
        self.assertEqual(actual["coverage_start"], "2026-04-09")
        self.assertEqual(actual["l5"]["points"], dict(average=4.0, valid_samples=4))
        self.assertEqual(actual["l5"]["minutes"], dict(average=32.25, valid_samples=4))
        self.assertEqual(actual["l5"]["assists"], dict(average=2.8, valid_samples=5))

    def test_supported_date_shapes_remain_calendar_dates(self):
        table = self.data["players"][0]["payload"]["resultSets"][0]
        table["rowSet"][0][table["headers"].index("GAME_DATE")] = "2026-04-20T00:00:00"
        self.write()
        _, observations = load_artifact(self.path)
        self.assertEqual(observations[0]["oracle"]["latest_appearance"], "2026-04-20")
        self.assertEqual(observations[0]["normalized"][0]["stats"]["_nba"]["date_precision"], "eastern_date")

    def test_invalid_and_zero_statistics_preserve_independent_denominators(self):
        table = self.data["players"][0]["payload"]["resultSets"][0]
        table["rowSet"] = table["rowSet"][:1]
        for field, value in {"PTS": 0, "REB": False, "AST": "bad", "MIN": "30:30"}.items():
            table["rowSet"][0][table["headers"].index(field)] = value
        self.write()
        _, observations = load_artifact(self.path)
        source = observations[0]["oracle"]["l5"]
        self.assertEqual(source["points"], dict(average=0, valid_samples=1))
        self.assertEqual(source["minutes"], dict(average=30.5, valid_samples=1))
        for metric in ("rebounds", "assists"):
            self.assertEqual(source[metric], dict(average=None, valid_samples=0))

    def test_import_replay_identity_and_summary_agree_with_raw_oracle(self):
        with Session(self.engine) as db, db.begin():
            first = seed_real_statistics_demo(db, self.path)[0]
            second = seed_real_statistics_demo(db, self.path)[0]
            self.assertEqual(first["imported"]["inserted"], 12)
            self.assertEqual(second["imported"]["unchanged"], 12)
            self.assertEqual(first["player_id"], IDENTITIES[0][2])
            player = db.get(Player, first["player_id"])
            logs = list(db.scalars(select(PlayerGameLog)))
            summary = build_nba_season_summary(player, logs, season="2025-26",
                reference=datetime.fromisoformat(first["reference_at"]), now=datetime(2026, 10, 18, 13, tzinfo=timezone.utc))
            for key in ("latest_appearance", "coverage_start", "coverage_end", "recorded_appearances"):
                self.assertEqual(summary[key], first["oracle"][key])
            for window in ("l5", "l10"):
                for metric in ("points", "rebounds", "assists", "minutes"):
                    self.assertEqual(summary[window][metric], first["oracle"][window][metric])
            prop = db.get(Prop, first["prop_id"])
            self.assertEqual(prop.line, 0)
            self.assertFalse(prop.is_active)
            self.assertIsNone(prop.over_odds)
            self.assertIsNone(prop.under_odds)
            self.assertEqual(list(db.scalars(select(PropBook))), [])

    def test_guard_precedes_file_read(self):
        with Session(self.engine) as db, patch("nba_real_statistics_demo._test_target", side_effect=ValueError("target")), \
                patch("nba_real_statistics_demo.load_artifact") as read:
            with self.assertRaisesRegex(ValueError, "target"):
                seed_real_statistics_demo(db, self.path)
            read.assert_not_called()

    def test_pending_application_changes_reject_before_artifact_read(self):
        with Session(self.engine) as db, patch("nba_real_statistics_demo.load_artifact") as read:
            db.add(Player(id=IDENTITIES[0][2], name="Pending unrelated work", team="A", team_abbr="A", sport="NBA"))
            with self.assertRaisesRegex(ValueError, "clean session"):
                seed_real_statistics_demo(db, self.path)
            read.assert_not_called()

    def test_later_player_failure_rolls_back_full_batch_without_actual_artifact(self):
        from app.services.nba_statistics_service import import_player_statistics
        second = deepcopy(self.data["players"][0])
        second["nba_player_id"] = "1627759"
        table = second["payload"]["resultSets"][0]
        for row in table["rowSet"]:
            row[table["headers"].index("Player_ID")] = 1627759
            row[table["headers"].index("MATCHUP")] = "BOS vs. LAL"
        self.data["players"].append(second)
        self.write()
        calls = 0
        def fail_later(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise ValueError("Forced later-player failure")
            return import_player_statistics(*args, **kwargs)
        with Session(self.engine) as db, db.begin(), patch(
                "nba_real_statistics_demo.import_player_statistics", side_effect=fail_later):
            with self.assertRaisesRegex(ValueError, "later-player"):
                seed_real_statistics_demo(db, self.path)
        with Session(self.engine) as db:
            for model in (Player, Event, Prop, PlayerGameLog):
                self.assertEqual(list(db.scalars(select(model))), [])

    def test_wrong_identity_or_season_or_future_observation_rejected(self):
        for mutate in (lambda d: d.update(season="2026-27"),
                       lambda d: d["players"][0].update(nba_player_id="1"),
                       lambda d: d["players"][0].update(observed_at="2099-01-01T00:00:00Z"),
                       lambda d: d["players"].append(deepcopy(d["players"][0]))):
            self.data = invented_artifact()
            mutate(self.data)
            self.write()
            with self.assertRaises(ValueError):
                load_artifact(self.path)

    def test_payload_player_cannot_cross_to_another_reviewed_player(self):
        table = self.data["players"][0]["payload"]["resultSets"][0]
        table["rowSet"][0][table["headers"].index("Player_ID")] = 1627759
        self.write()
        with self.assertRaises(ValueError):
            load_artifact(self.path)

    def test_collision_rolls_back_new_records_atomically(self):
        with Session(self.engine) as db, db.begin():
            db.add(Event(id="5d000010-0000-4000-8000-000000000001", provider="existing",
                provider_event_id="collision", sport_key="basketball_nba", home_team="A", away_team="B",
                scheduled_start_at=datetime(2026, 1, 1)))
        with Session(self.engine) as db, db.begin():
            with self.assertRaisesRegex(ValueError, "collision"):
                seed_real_statistics_demo(db, self.path)
        with Session(self.engine) as db:
            self.assertEqual(list(db.scalars(select(Player))), [])
            self.assertEqual(list(db.scalars(select(PlayerGameLog))), [])
            self.assertEqual(list(db.scalars(select(Prop))), [])

    def test_existing_espn_row_is_preserved(self):
        with Session(self.engine) as db, db.begin():
            seed_real_statistics_demo(db, self.path)
            db.add(PlayerGameLog(player_id=IDENTITIES[0][2], external_game_id="0022500000", source="espn_nba",
                sport="NBA", game_date=datetime(2026, 4, 20), stats={"points": 99}))
        with Session(self.engine) as db, db.begin():
            seed_real_statistics_demo(db, self.path)
            logs = list(db.scalars(select(PlayerGameLog)))
            self.assertEqual(len(logs), 13)
            self.assertEqual(next(row for row in logs if row.source == "espn_nba").stats, {"points": 99})


@unittest.skipUnless(pg_fixture.TEST_URL and os.environ.get("PROPPULSE_NBA_STATISTICS_DEMO_FILE"),
    "Explicit disposable PostgreSQL URL and authorized actual artifact required")
class ActualStatisticsPostgresTests(unittest.TestCase):
    """Opt-in real artifact checks; no application lifespan or provider transport."""
    remove_schema = pg_fixture.EventMigrationPostgresTests.remove_schema
    upgrade = pg_fixture.EventMigrationPostgresTests.upgrade
    snapshot = pg_fixture.EventMigrationPostgresTests.snapshot

    @classmethod
    def setUpClass(cls):
        from integration_server import integration_target
        from app.services.nba_evidence_service import _test_target
        cls.target = integration_target(pg_fixture.TEST_URL)
        engine = create_engine(cls.target)
        try:
            with Session(engine) as db:
                _test_target(db)  # Physical-target guard before schema DDL.
        finally:
            engine.dispose()

    def setUp(self):
        pg_fixture.EventMigrationPostgresTests.setUp(self)
        self.upgrade("20261018_04")
        self.path = os.environ["PROPPULSE_NBA_STATISTICS_DEMO_FILE"]

    def test_actual_artifact_database_and_read_only_research_api_agree(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.players import router
        artifact, observations = load_artifact(self.path)
        untouched = {table.name for table in Base.metadata.sorted_tables} - {
            "players", "events", "props", "player_game_logs", "nba_evidence_records"}
        before = self.snapshot(Base.metadata)
        with Session(self.engine) as db, db.begin():
            manifests = seed_real_statistics_demo(db, self.path)
        seeded = self.snapshot(Base.metadata)
        for table in untouched:
            self.assertEqual(seeded[table], before[table], table)
        with Session(self.engine) as db, db.begin():
            repeated = seed_real_statistics_demo(db, self.path)
        self.assertEqual(self.snapshot(Base.metadata), seeded)
        for actual, replay, observation in zip(manifests, repeated, observations, strict=True):
            expected = observation["oracle"]
            self.assertEqual(actual["imported"]["inserted"], len(observation["normalized"]))
            self.assertEqual(replay["imported"]["unchanged"], len(observation["normalized"]))
            with Session(self.engine) as db:
                rows = list(db.scalars(select(PlayerGameLog).where(PlayerGameLog.player_id == actual["player_id"])))
                raw = {row["Game_ID"]: row for row in _rows(observation["payload"])}
                self.assertEqual({row.external_game_id for row in rows}, {f"nba_com:{game}" for game in raw})
                for row in rows:
                    self.assertEqual(row.source, "nba_com_stats")
                    self.assertEqual(row.stats["_nba"]["nba_player_id"], actual["nba_player_id"])
                    self.assertEqual(row.stats["_nba"]["season"], "2025-26")
                    self.assertEqual(row.stats["_nba"]["competition"], "Regular Season")
                    self.assertEqual(row.stats["_nba"]["observed_at"], observation["observed"].isoformat())
                by_game = {row.stats["_nba"]["nba_game_id"]: row for row in rows}
                for window in ("l5", "l10"):
                    for sample in expected[window]["samples"]:
                        for metric in ("points", "rebounds", "assists", "minutes"):
                            self.assertEqual(by_game[sample["game_id"]].stats[metric], sample[metric])
                # Stored paired team evidence must match both exact raw NBA game
                # identities and reciprocal participants, never approximate dates.
                if artifact.get("team"):
                    table = next(t for t in artifact["team"]["payload"]["resultSets"] if t["name"] == "LeagueGameLog")
                    grouped = {}
                    for values in table["rowSet"]:
                        record = dict(zip(table["headers"], values, strict=True))
                        grouped.setdefault(record["GAME_ID"], []).append(record)
                    games = list(db.scalars(select(NBAEvidenceRecord).where(NBAEvidenceRecord.kind == "game")))
                    self.assertGreater(len(games), 0)
                    for game in games:
                        pair = grouped[game.identity]
                        self.assertEqual(len(pair), 2)
                        self.assertEqual({str(r["TEAM_ID"]) for r in pair},
                            {game.payload["home_team_id"], game.payload["away_team_id"]})
                        self.assertEqual({r["WL"] for r in pair}, {"W", "L"})
        app = FastAPI()
        app.include_router(router, prefix="/players")
        def database():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = database
        statements = []
        @event.listens_for(self.engine, "before_cursor_execute")
        def capture(_conn, _cursor, statement, *_args):
            statements.append(statement)
        with patch("requests.sessions.Session.request", side_effect=AssertionError("No provider HTTP")), TestClient(app) as client:
            for manifest in manifests:
                response = client.get(f"/players/{manifest['player_id']}/research", params={
                    "prop_id": manifest["prop_id"], "season": "2025-26", "competition": "Regular Season"})
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["selected_prop"]["id"], manifest["prop_id"])
                summary = body["season_summary"]
                for key in ("latest_appearance", "coverage_start", "coverage_end", "recorded_appearances"):
                    self.assertEqual(summary[key], manifest["oracle"][key])
                for window in ("l5", "l10"):
                    for metric in ("points", "rebounds", "assists", "minutes"):
                        self.assertEqual(summary[window][metric], manifest["oracle"][window][metric])
        self.assertTrue(statements)
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement in statements))
        event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(self.snapshot(Base.metadata), seeded)

    def test_actual_multiplayer_batch_failure_is_atomic(self):
        from app.services.nba_statistics_service import import_player_statistics
        _, observations = load_artifact(self.path)
        if len(observations) < 2:
            self.skipTest("Multiplayer rollback requires at least two returned player observations")
        before = self.snapshot(Base.metadata)
        calls = 0
        def fail_second_player(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:  # First player + replay succeeded; next player fails.
                raise ValueError("Forced later-player failure")
            return import_player_statistics(*args, **kwargs)
        with Session(self.engine) as db, db.begin(), patch(
                "nba_real_statistics_demo.import_player_statistics", side_effect=fail_second_player):
            with self.assertRaisesRegex(ValueError, "later-player"):
                seed_real_statistics_demo(db, self.path)
        self.assertEqual(self.snapshot(Base.metadata), before)


if __name__ == "__main__":
    unittest.main()
