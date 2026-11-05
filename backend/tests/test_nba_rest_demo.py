"""Offline 4A.6 rehearsal, never a claim of a successful real-data demo."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Event, NBAEvidenceRecord, Player, PlayerGameLog, Prop, PropBook, PropBookSnapshot
from app.routers.players import router
from app.services.nba_api_provider import normalize_player_games, normalize_team_games, verified_crosswalk
from app.services.nba_evidence_service import load_verified_evidence
from app.services.rest_workload_service import build_verified_rest, build_rest_workload
from nba_rest_demo_fixture import (
    GAME_DATE, MANIFEST, NOW, OBSERVED, REFERENCE, normalized_fixture, reviewed_crosswalk, seed, synthetic_payloads,
)
from nba_real_rest_demo import IDENTITIES, seed_real_demo
import test_event_migration_postgres as pg_fixture


class DemoScenarios:
    def test_browser_target_rejects_ambient_libpq_before_connection(self):
        from integration_server import integration_target
        for key in ("PGHOSTADDR", "PGSERVICE", "PGOPTIONS", "PGDATABASE"):
            with self.subTest(key=key), patch.dict(os.environ, {key: "unsafe-fixture-routing"}), \
                    patch("sqlalchemy.create_engine", side_effect=AssertionError("No connection permitted")):
                with self.assertRaisesRegex(RuntimeError, "Ambient libpq"):
                    integration_target("postgresql://postgres@127.0.0.1:52467/proppulse_test_4a6_final")

    def setup_demo(self):
        blocker = patch("requests.sessions.Session.request", side_effect=AssertionError("Provider HTTP forbidden in offline 4A.6 tests"))
        blocker.start()
        self.addCleanup(blocker.stop)
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        # Two dedicated crosswalk demonstrations must use independent stores;
        # they deliberately assign different local UUIDs to the public athletes.
        if self._testMethodName != "test_real_artifact_loader_with_explicitly_synthetic_contract_fixture":
            seed(self.db)
            self.db.commit()

    def result(self, item=MANIFEST[0], reference=REFERENCE):
        evidence, _ = load_verified_evidence(self.db, item["player_id"], now=NOW)
        return build_verified_rest(item["player_id"], reference=reference, now=NOW, evidence=evidence)

    def test_explicit_reviewed_real_identity_directory_and_dedicated_uuids(self):
        crosswalk = reviewed_crosswalk()
        for item in MANIFEST:
            self.assertEqual(crosswalk[item["nba_player_id"]], item["player_id"])
            self.assertIn("synthetic game results", crosswalk.provenance[item["nba_player_id"]])
            self.assertEqual(self.db.get(Player, item["player_id"]).name, item["name"])
        entries = [dict(nba_player_id=i["nba_player_id"], player_id=MANIFEST[0]["player_id"], verified=True,
                        provenance="Explicit conflict test") for i in MANIFEST]
        with self.assertRaises(ValueError):
            verified_crosswalk(entries)

    def test_unknown_and_conflicting_identity_fail_closed(self):
        teams, payload = synthetic_payloads(MANIFEST[0])
        games = normalize_team_games(teams, observed_at=OBSERVED)["records"]
        unknown = normalize_player_games(payload, observed_at=OBSERVED, crosswalk={}, game_records=games)
        self.assertEqual(unknown["records"], [])
        self.assertTrue(unknown["issues"])
        original = self.db.get(Player, MANIFEST[0]["player_id"])
        original.name = "Conflicting identity"
        self.db.flush()
        with self.assertRaisesRegex(ValueError, "collision"):
            seed(self.db)
        self.db.rollback()

    def test_synthetic_source_shaped_normalization_and_date_only_provenance(self):
        records = normalized_fixture(reviewed_crosswalk())
        games = [r for r in records if r["kind"] == "game"]
        self.assertEqual(len(games), 2)
        for game in games:
            self.assertEqual(game["payload"]["game_at"], GAME_DATE + "T05:00:00+00:00")
            self.assertIsNone(game["payload"]["completed_at"])
            self.assertEqual(game["payload"]["time_precision"], "eastern_date")
        self.assertFalse(any(r["kind"] in {"membership", "coverage"} for r in records))

    def test_last_recorded_appearance_eastern_days_and_unknown_context(self):
        for item in MANIFEST:
            result = self.result(item)
            appearance = result["last_confirmed_appearance"]
            self.assertEqual(appearance["gap_days"], 3)  # UTC Jan19 is Eastern Jan18.
            self.assertEqual(appearance["full_rest_days"], 2)
            self.assertEqual(appearance["time_precision"], "eastern_date")
            self.assertEqual(appearance["provider"], "nba_com")
            self.assertIsNone(result["last_completed_team_game"])
            self.assertIsNone(result["confirmed_missed_games"])
            self.assertIsNone(result["team_back_to_back"])
            self.assertFalse(result["schedule_complete"])

    def test_historical_reference_excludes_later_appearance(self):
        result = self.result(reference=datetime(2021, 1, 15, 4, tzinfo=timezone.utc))
        self.assertIsNone(result["last_confirmed_appearance"])

    def test_actual_later_observation_cannot_be_backdated_to_historical_reference(self):
        evidence, _ = load_verified_evidence(self.db, MANIFEST[0]["player_id"], now=NOW)
        actual_observation = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
        evidence = replace(evidence,
            games=tuple(replace(game, observed_at=actual_observation) for game in evidence.games),
            participation=tuple(replace(row, observed_at=actual_observation) for row in evidence.participation))
        result = build_verified_rest(MANIFEST[0]["player_id"], reference=REFERENCE,
                                     now=actual_observation, evidence=evidence)
        self.assertIsNone(result["last_confirmed_appearance"])
        self.assertIsNone(result["confirmed_missed_games"])

    def test_repeated_seed_is_idempotent_and_never_populates_minutes(self):
        before = self.db.scalar(select(func.count()).select_from(NBAEvidenceRecord))
        seed(self.db)
        self.db.commit()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(NBAEvidenceRecord)), before)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(PlayerGameLog)), 0)
        for item in MANIFEST:
            self.assertIsNone(self.db.get(Prop, item["prop_id"]).over_odds)
            workload = build_rest_workload(self.db.get(Player, item["player_id"]), [],
                event=self.db.get(Event, item["event_id"]), prop=self.db.get(Prop, item["prop_id"]), now=NOW)
            self.assertIsNone(workload["workload"]["l5"]["average_minutes"])
            self.assertIsNone(workload["workload"]["l10"]["average_minutes"])

    def test_evidence_does_not_replace_existing_statistical_minutes_windows(self):
        item = MANIFEST[0]
        # Separate statistical-pipeline inputs, deliberately not seeded for UI.
        logs = [SimpleNamespace(id=f"offline-stat-{index}", player_id=item["player_id"], sport="NBA",
                    external_game_id=f"offline-stat-{index}", game_date=REFERENCE - timedelta(days=index + 1),
                    stats={"minutes": 20 + index, "points": 10}, source="espn_nba", opponent="Synthetic",
                    is_home=True) for index in range(10)]
        args = dict(event=self.db.get(Event, item["event_id"]), prop=self.db.get(Prop, item["prop_id"]), now=NOW)
        player = self.db.get(Player, item["player_id"])
        before = build_rest_workload(player, logs, **args)
        evidence, _ = load_verified_evidence(self.db, item["player_id"], now=NOW)
        after = build_rest_workload(player, logs, verified_evidence=evidence, **args)
        self.assertEqual(before["workload"], after["workload"])
        self.assertEqual(after["workload"]["l5"]["average_minutes"], 22)
        self.assertEqual(after["workload"]["l10"]["average_minutes"], 24.5)
        self.assertEqual(after["workload"]["minutes_trend"], -5)

    def test_research_is_read_only_and_preserves_exact_selection_and_no_logs(self):
        app = FastAPI()
        app.include_router(router, prefix="/players")
        app.dependency_overrides[get_db] = lambda: self.db
        statements = []
        def capture(conn, cursor, statement, *args):
            statements.append(statement.lstrip().split()[0].upper())
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with TestClient(app) as client:
                for item in MANIFEST:
                    response = client.get(f"/players/{item['player_id']}/research", params={"prop_id": item["prop_id"]})
                    self.assertEqual(response.status_code, 200, response.text)
                    body = response.json()
                    self.assertEqual(body["selected_prop"]["id"], item["prop_id"])
                    self.assertEqual(body["selected_prop"]["event_id"], item["event_id"])
                    rest = body["rest_workload"]
                    self.assertEqual(rest["player_id"], item["player_id"])
                    self.assertEqual(rest["reference"]["at"], REFERENCE.isoformat())
                    self.assertEqual(rest["verified"]["last_confirmed_appearance"]["gap_days"], 3)
                    self.assertIsNone(rest["workload"]["l5"]["average_minutes"])
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)
        self.assertFalse(set(statements) & {"INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP"})

    def test_real_artifact_loader_with_explicitly_synthetic_contract_fixture(self):
        # Tests loader semantics only. This invented artifact is not actual NBA
        # evidence; real observation verification is reported separately.
        observed = "2026-10-18T20:58:08.542417+00:00"
        identities = [dict(nba_player_id=nba, player_id=local, verified=True,
                           provenance=f"Synthetic loader contract fixture for {name}") for nba, name, local in IDENTITIES]
        records = normalized_fixture(verified_crosswalk(identities))
        for row in records:
            row["observed_at"] = observed
        artifact = dict(actual_source=True, raw_retained=False, requests=3, issues=[],
                        observed_at=observed, identities=identities, records=records)
        with TemporaryDirectory(prefix="proppulse_test_4a6_") as directory:
            path = Path(directory) / "synthetic-normalized-contract.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            selected = seed_real_demo(self.db, path)
            self.db.commit()
            count = self.db.scalar(select(func.count()).select_from(NBAEvidenceRecord))
            seed_real_demo(self.db, path)
            self.db.commit()
            self.assertEqual(self.db.scalar(select(func.count()).select_from(NBAEvidenceRecord)), count)
            for item in selected:
                evidence, _ = load_verified_evidence(self.db, item["player_id"])
                result = build_verified_rest(item["player_id"], reference=datetime.fromisoformat(item["reference_at"]),
                                             now=datetime.now(timezone.utc), evidence=evidence)
                self.assertEqual(result["last_confirmed_appearance"]["gap_days"], 2102)
                self.assertEqual(result["last_confirmed_appearance"]["full_rest_days"], 2101)
                historical = build_verified_rest(item["player_id"], reference=REFERENCE,
                                             now=datetime.now(timezone.utc), evidence=evidence)
                self.assertIsNone(historical["last_confirmed_appearance"])
                self.assertIsNone(self.db.get(Prop, item["prop_id"]).over_odds)
                self.assertEqual(self.db.get(Event, item["event_id"]).provider, "synthetic_fixture_4a6_real_reference")
            self.db.get(Player, selected[0]["player_id"]).name = "Conflicting identity"
            self.db.flush()
            with self.assertRaisesRegex(ValueError, "collision"):
                seed_real_demo(self.db, path)
            self.db.rollback()

    def test_real_loader_target_guard_runs_before_file_access(self):
        with patch("nba_real_rest_demo._test_target", side_effect=ValueError("Unsafe target")), \
             patch("nba_real_rest_demo.Path") as path:
            with self.assertRaisesRegex(ValueError, "Unsafe target"):
                seed_real_demo(self.db, "never-open-this-file.json")
            path.assert_not_called()


class DemoSQLiteTests(DemoScenarios, unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine, tables=[m.__table__ for m in
            (Player, Event, Prop, PropBook, PropBookSnapshot, PlayerGameLog, NBAEvidenceRecord)])
        self.setup_demo()


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit owned disposable PostgreSQL required")
class DemoPostgresTests(DemoScenarios, unittest.TestCase):
    def setUp(self):
        cls = pg_fixture.EventMigrationPostgresTests
        cls.setUpClass()
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.upgrade("20261018_04")
        self.assertEqual(fixture.revision(), "20261018_04")
        self.engine = fixture.engine
        self.setup_demo()
