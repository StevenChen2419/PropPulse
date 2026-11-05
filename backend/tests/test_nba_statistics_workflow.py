"""Reusable import tests use invented responses and disposable PostgreSQL only."""
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.database import Base, get_db
from app.models import Event, Player, PlayerGameLog, Prop
from app.routers.players import router
from app.services.nba_statistics_service import import_player_statistics
from app.services.nba_statistics_workflow import prepare_batch, run_import
import test_event_migration_postgres as pg_fixture
from scripts import import_nba_statistics as import_cli


SCOPE = dict(season="2025-26", competition="Regular Season",
             date_from="2025-10-01", date_to="2026-06-30")
OBSERVED = "2026-10-18T12:00:00+00:00"


def fixture():
    mappings, responses = [], []
    for index, athlete in enumerate(("1630595", "1628369")):
        mappings.append(dict(player_id=str(uuid4()), nba_player_id=athlete,
            player_name=f"Invented Fixture {index}", review_status="verified",
            provenance="Independent synthetic fixture assertion; no real identity claimed"))
        rows = [dict(Player_ID=int(athlete), Game_ID=f"00225000{i:02d}", SEASON_ID="22025",
            GAME_DATE=f"APR {20-i:02d}, 2026", MATCHUP="BOS vs. ORL", WL='W', MIN=30+i,
            PTS=i*2, REB=i, AST=i+1) for i in range(12)]
        rows[1]["MIN"] = None
        rows[2]["PTS"] = None
        responses.append(dict(nba_player_id=athlete, observed_at=OBSERVED,
            payload={"resultSets": [dict(name="PlayerGameLog", headers=list(rows[0]),
                rowSet=[list(row.values()) for row in rows])]}))
    return mappings, dict(**SCOPE, responses=responses)


class WorkflowValidationTests(unittest.TestCase):
    def setUp(self):
        self.mappings, self.artifact = fixture()

    def prepare(self, **changes):
        return prepare_batch(self.mappings, self.artifact, **(SCOPE | changes))

    def test_multiple_players_and_explicit_single_player_selection(self):
        self.assertEqual(self.prepare()["total_records"], 24)
        self.artifact["responses"] = self.artifact["responses"][:1]
        batch = self.prepare(player_ids=[self.mappings[0]["player_id"]])
        self.assertEqual(batch["total_records"], 12)
        self.assertEqual(len(batch["players"]), 1)

    def test_batch_has_no_three_player_limit(self):
        template_mapping, template_response = self.mappings[0], self.artifact["responses"][0]
        self.mappings, self.artifact["responses"] = [], []
        for index in range(21):
            athlete = str(7000000 + index)
            self.mappings.append(dict(template_mapping, player_id=str(uuid4()), nba_player_id=athlete))
            response = deepcopy(template_response)
            response["nba_player_id"] = athlete
            table = response["payload"]["resultSets"][0]
            for row in table["rowSet"]:
                row[table["headers"].index("Player_ID")] = int(athlete)
            self.artifact["responses"].append(response)
        self.assertEqual(len(self.prepare()["players"]), 21)
        self.assertEqual(self.prepare()["total_records"], 252)

    def test_unreviewed_mapping_skipped_without_guessing(self):
        self.mappings[1]["review_status"] = "candidate"
        self.artifact["responses"].pop()
        batch = self.prepare()
        self.assertEqual(batch["total_records"], 12)
        self.assertEqual(batch["skipped"][0]["player_id"], self.mappings[1]["player_id"])
        self.assertTrue(batch["skipped"][0]["reason"])

    def test_mapping_conflicts_or_missing_provenance_rejected(self):
        for key in ("player_id", "nba_player_id"):
            mappings = deepcopy(self.mappings)
            mappings[1][key] = mappings[0][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                prepare_batch(mappings, self.artifact, **SCOPE)
        self.mappings[0]["provenance"] = ""
        with self.assertRaises(ValueError):
            self.prepare()

    def test_wrong_season_competition_date_or_row_budget_rejected(self):
        for changes in (dict(season="2024-25"), dict(competition="Pre Season"),
                        dict(date_from="2025-09-30"), dict(date_to="2026-07-01"),
                        dict(max_rows=23), dict(max_rows=0)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.prepare(**changes)
        self.artifact["season"] = "2026-27"
        with self.assertRaises(ValueError):
            self.prepare()

    def test_response_outside_requested_date_or_identity_rejected(self):
        for field, value in (("GAME_DATE", "SEP 30, 2025"), ("Player_ID", 2544),
                             ("SEASON_ID", "22026"), ("Game_ID", "0042500001")):
            artifact = deepcopy(self.artifact)
            table = artifact["responses"][0]["payload"]["resultSets"][0]
            table["rowSet"][0][table["headers"].index(field)] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                prepare_batch(self.mappings, artifact, **SCOPE)

    def test_missing_or_unexpected_response_rejected(self):
        self.artifact["responses"].pop()
        with self.assertRaises(ValueError):
            self.prepare()
        self.artifact["responses"].append(dict(nba_player_id="2544", observed_at=OBSERVED, payload={}))
        with self.assertRaises(ValueError):
            self.prepare()

    def test_current_scope_before_regular_season_has_no_collectable_interval(self):
        current = dict(season="2026-27", competition="Regular Season",
                       date_from="2026-10-19", date_to="2026-10-19")
        with self.assertRaises(ValueError):
            prepare_batch(self.mappings, dict(**current, responses=[]), **current)


class WorkflowCommandTests(unittest.TestCase):
    """Exercise approval binding without creating any database connections."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        mappings, artifact = fixture()
        for name, data in (("mapping", mappings), ("artifact", artifact)):
            (self.folder / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
        self.args = ["--mapping", str(self.folder / "mapping.json"), "--artifact",
            str(self.folder / "artifact.json"), "--season", "2025-26", "--competition",
            "Regular Season", "--date-from", "2025-10-01", "--date-to", "2026-06-30", "--max-rows", "24"]
        self.settings = SimpleNamespace(DATABASE_URL="postgresql://fixture:secret-test-only@localhost:5432/proppulse",
                                        ENVIRONMENT="development", LIVE_REFRESH_ENABLED=False)

    def invoke(self, extra=(), **settings_changes):
        configured = SimpleNamespace(**(vars(self.settings) | settings_changes))
        stdout, stderr, engine = io.StringIO(), io.StringIO(), Mock()
        with patch.dict(import_cli.os.environ, {}, clear=True), patch("app.config.settings", configured), \
                patch("sqlalchemy.create_engine", return_value=engine) as connect, \
                patch("app.services.nba_statistics_workflow.run_import", return_value={"mode": "mock"}) as run, \
                patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = import_cli.main(self.args + list(extra))
        return code, stdout.getvalue(), stderr.getvalue(), connect, run, engine

    def approve(self, scope):
        path = self.folder / "approval.json"
        path.write_text(json.dumps(scope), encoding="utf-8")
        return ["--execute", "--approval", str(path)]

    def test_default_is_read_only_and_returns_bound_approval_scope(self):
        code, out, err, connect, run, engine = self.invoke()
        self.assertEqual(code, 0, err)
        self.assertIs(run.call_args.kwargs["execute"], False)
        scope = json.loads(out)["approval_scope"]
        self.assertEqual(scope["max_rows"], 24)
        self.assertEqual(len(scope["player_ids"]), 2)
        self.assertEqual(scope["database_target"]["database"], "proppulse")
        self.assertNotIn("secret-test-only", out + err)
        self.assertEqual(len(scope["mapping_sha256"]), 64)
        self.assertEqual(len(scope["artifact_sha256"]), 64)
        connect.assert_called_once()
        engine.dispose.assert_called_once()

    def test_execution_requires_exact_approval_and_all_bindings(self):
        code, out, err, *_ = self.invoke()
        self.assertEqual(code, 0, err)
        scope = json.loads(out)["approval_scope"]
        for key, wrong in (("mapping_sha256", "0" * 64), ("artifact_sha256", "0" * 64),
                           ("player_ids", []), ("max_rows", 25), ("season", "2026-27"),
                           ("competition", "Playoffs"), ("date_from", "2025-10-02"),
                           ("date_to", "2026-06-29"), ("database_target", {"database": "other"})):
            with self.subTest(key=key):
                code, _, err, connect, run, _ = self.invoke(self.approve(scope | {key: wrong}))
                self.assertEqual(code, 1)
                self.assertIn("approval", err.lower())
                connect.assert_not_called()
                run.assert_not_called()
        code, _, err, connect, run, _ = self.invoke(["--execute"])
        self.assertEqual(code, 1)
        connect.assert_not_called()
        run.assert_not_called()
        code, _, err, connect, run, engine = self.invoke(self.approve(scope))
        self.assertEqual(code, 0, err)
        self.assertIs(run.call_args.kwargs["execute"], True)
        engine.dispose.assert_called_once()

    def test_non_development_refresh_or_redirected_database_refused(self):
        for changes in (dict(ENVIRONMENT="production"), dict(ENVIRONMENT="staging"),
                        dict(ENVIRONMENT="test"), dict(LIVE_REFRESH_ENABLED=True),
                        dict(DATABASE_URL="postgresql://fixture:secret-test-only@localhost:5433/proppulse"),
                        dict(DATABASE_URL="postgresql://fixture:secret-test-only@remote.invalid:5432/proppulse"),
                        dict(DATABASE_URL="postgresql://fixture:secret-test-only@localhost:5432/other"),
                        dict(DATABASE_URL="postgresql://fixture:secret-test-only@localhost:5432/proppulse?host=other")):
            with self.subTest(changes=list(changes)):
                code, out, err, connect, run, _ = self.invoke(**changes)
                self.assertEqual(code, 1)
                self.assertNotIn("secret-test-only", out + err)
                connect.assert_not_called()
                run.assert_not_called()


@unittest.skipUnless(pg_fixture.TEST_URL, "Explicit disposable PostgreSQL URL unset")
class WorkflowPostgresTests(unittest.TestCase):
    setUpClass = classmethod(pg_fixture.EventMigrationPostgresTests.setUpClass.__func__)
    remove_schema = pg_fixture.EventMigrationPostgresTests.remove_schema

    def setUp(self):
        pg_fixture.EventMigrationPostgresTests.setUp(self)
        Base.metadata.create_all(self.engine)
        self.mappings, self.artifact = fixture()
        self.batch = prepare_batch(self.mappings, self.artifact, **SCOPE)
        self.event_id, self.prop_id = str(uuid4()), str(uuid4())
        with Session(self.engine) as db, db.begin():
            for mapping in self.mappings:
                db.add(Player(id=mapping["player_id"], name=mapping["player_name"],
                    team="Boston Celtics", team_abbr="BOS", sport="NBA"))
            db.flush()
            db.add(Event(id=self.event_id, provider="the_odds_api", provider_event_id="invented-event",
                sport_key="basketball_nba", home_team="Boston Celtics", away_team="Orlando Magic",
                scheduled_start_at=datetime(2026, 10, 21, 23)))
            db.flush()
            db.add(Prop(id=self.prop_id, player_id=self.mappings[0]["player_id"], event_id=self.event_id,
                prop_type="points", line=20.5, game_time=datetime(2026, 10, 21, 23), opponent="ORL"))
            db.add(PlayerGameLog(player_id=self.mappings[0]["player_id"], sport="NBA",
                external_game_id="0022500000", source="espn_nba", game_date=datetime(2026, 4, 20),
                stats={"points": 99, "minutes": 42}))

    def snapshot(self):
        with self.engine.connect() as connection:
            return {table.name: [dict(row) for row in connection.execute(select(table).order_by(table.c.id)).mappings()]
                    for table in Base.metadata.sorted_tables}

    def run_batch(self, **kwargs):
        return run_import(self.engine, self.batch, allow_test_database=True, **kwargs)

    def test_default_dry_run_is_select_only_and_preserves_all_tables(self):
        before, statements = self.snapshot(), []
        def capture(_conn, _cursor, statement, *_args):
            statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            result = self.run_batch()
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(sum(row["added"] for row in result["players"]), 24)
        self.assertTrue(statements)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") or
                            sql.strip().upper() == "SET TRANSACTION READ ONLY" for sql in statements))
        self.assertEqual(self.snapshot(), before)

    def test_import_reimport_and_espn_preservation(self):
        before = self.snapshot()
        self.assertEqual(sum(p["added"] for p in self.run_batch(execute=True)["players"]), 24)
        first = self.snapshot()
        self.assertEqual(sum(p["unchanged"] for p in self.run_batch(execute=True)["players"]), 24)
        self.assertEqual(self.snapshot(), first)
        for table, rows in before.items():
            if table != "player_game_logs":
                self.assertEqual(first[table], rows)
        retained = next(row for row in first["player_game_logs"] if row["source"] == "espn_nba")
        self.assertEqual(retained, before["player_game_logs"][0])
        self.assertEqual({row["external_game_id"] for row in first["player_game_logs"] if row["source"] == "nba_com_stats"},
                         {f"nba_com:00225000{i:02d}" for i in range(12)})

    def test_later_player_failure_rolls_back_complete_batch(self):
        before = self.snapshot()
        calls = 0
        def fail_later(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("Injected later player failure")
            return import_player_statistics(*args, **kwargs)
        with patch("app.services.nba_statistics_workflow.import_player_statistics", side_effect=fail_later):
            with self.assertRaisesRegex(ValueError, "later player"):
                self.run_batch(execute=True)
        self.assertEqual(calls, 2)
        self.assertEqual(self.snapshot(), before)

    def test_stored_identity_conflict_rejected_without_writes(self):
        self.run_batch(execute=True)
        before = self.snapshot()
        self.batch["players"][0]["nba_player_id"] = "2544"
        with self.assertRaises(ValueError):
            self.run_batch(execute=True)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_local_player_refused_and_partial_sample_stays_partial(self):
        before = self.snapshot()
        mappings = deepcopy(self.mappings)
        mappings[0]["player_id"] = str(uuid4())
        self.batch = prepare_batch(mappings, self.artifact, **SCOPE)
        with self.assertRaises(ValueError):
            self.run_batch(execute=True)
        self.assertEqual(self.snapshot(), before)
        for response in self.artifact["responses"]:
            response["payload"]["resultSets"][0]["rowSet"] = response["payload"]["resultSets"][0]["rowSet"][:1]
        self.batch = prepare_batch(self.mappings, self.artifact, **SCOPE)
        self.run_batch(execute=True)
        from app.services.nba_season_summary import build_nba_season_summary
        with Session(self.engine) as db:
            player = db.get(Player, self.mappings[0]["player_id"])
            logs = list(db.scalars(select(PlayerGameLog).where(PlayerGameLog.player_id == player.id)))
            summary = build_nba_season_summary(player, logs, season="2025-26",
                now=datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
            self.assertEqual(summary["l5"]["appearances"], 1)
            self.assertEqual(summary["l10"]["appearances"], 1)
            self.assertEqual(summary["l10"]["points"], dict(average=0, valid_samples=1))

    def test_research_uses_stored_samples_exact_selection_and_no_provider_http(self):
        self.run_batch(execute=True)
        before = self.snapshot()
        app = FastAPI()
        app.include_router(router, prefix="/players")
        def database():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = database
        with patch("requests.sessions.Session.request", side_effect=AssertionError("No provider HTTP")), TestClient(app) as client:
            url = f"/players/{self.mappings[0]['player_id']}/research"
            player_only = client.get(url, params={"season": "2025-26", "competition": "Regular Season"})
            self.assertEqual(player_only.status_code, 200)
            summary = player_only.json()["season_summary"]
            self.assertEqual(summary["l5"]["points"], dict(average=4, valid_samples=4))
            self.assertEqual(summary["l10"]["points"], dict(average=9.56, valid_samples=9))
            self.assertEqual(summary["l5"]["minutes"], dict(average=32.25, valid_samples=4))
            linked = client.get(url, params={"prop_id": self.prop_id, "season": "2025-26"})
            self.assertEqual(linked.status_code, 200)
            self.assertEqual(linked.json()["selected_prop"]["id"], self.prop_id)
            self.assertEqual(linked.json()["selected_prop"]["event_id"], self.event_id)
            current = client.get(url, params={"season": "2026-27"})
            self.assertEqual(current.status_code, 200)
            self.assertEqual(current.json()["season_summary"]["status"], "unavailable")
        self.assertEqual(self.snapshot(), before)
