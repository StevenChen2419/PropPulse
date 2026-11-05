"""Synthetic manifests and isolated stores; no real provider or application DB."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import make_url

from app.database import Base, get_db
from app.models import Event, NBAEvidenceRecord, Player, PlayerGameLog, Prop, PropBook, PropBookSnapshot
from app.routers.players import router
from app.services.nba_evidence_service import reconcile_fixture, load_verified_evidence, _test_target
from app.services.rest_workload_service import build_verified_rest
from participation_fixture import participation_manifest
import test_event_migration_postgres as pg_fixture

UTC = timezone.utc


class EvidenceScenarios:
    def fixture(self):
        self.now = datetime.now(UTC)
        self.player = Player(name="Persisted Fixture", team="Mutable Wrong Team", team_abbr="WRG", sport="NBA")
        self.other = Player(name="Partial Fixture", team="Other Wrong Team", team_abbr="WRG", sport="NBA")
        self.db.add_all([self.player, self.other])
        self.db.flush()
        self.manifest, self.reference, self.later = participation_manifest(self.now,
            confirmed_player_id=self.player.id, partial_player_id=self.other.id)
        self.scope = {"sport": "NBA", "start_date": self.manifest["date_start"],
                      "end_date": self.manifest["date_end"], "team_ids": self.manifest["team_ids"]}
        self.event = Event(provider="the_odds_api", sport_key="basketball_nba", provider_event_id="existing-odds-fixture",
                           home_team="Unrelated Labels", away_team="Another Label", scheduled_start_at=self.reference)
        self.db.add(self.event)
        self.db.flush()
        self.prop = Prop(player_id=self.player.id, event_id=self.event.id, prop_type="points", line=20,
                         game_time=self.later, is_active=False, sportsbook="Fixture Book")
        self.db.add_all([self.prop, PlayerGameLog(player_id=self.player.id, sport="NBA", source="espn_nba",
            external_game_id="existing-statistical-log", game_date=self.reference - timedelta(days=4),
            stats={"points": 30, "minutes": 35})])
        self.db.commit()
        app = FastAPI()
        app.include_router(router, prefix="/players")
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def persist(self, manifest=None):
        manifest = manifest or self.manifest
        dry = reconcile_fixture(self.db, manifest, **self.scope, now=self.now)
        result = reconcile_fixture(self.db, manifest, **self.scope, now=self.now,
                                   write=True, expected_digest=dry["digest"])
        self.db.commit()
        return result

    def result(self, player=None, reference=None):
        evidence, notes = load_verified_evidence(self.db, (player or self.player).id, now=self.now)
        value = build_verified_rest((player or self.player).id,
                    reference=(reference or self.reference).replace(tzinfo=UTC), now=self.now, evidence=evidence)
        value["notes"].extend(notes)
        return value

    def count(self):
        return self.db.scalar(select(func.count()).select_from(NBAEvidenceRecord))

    def subset(self, records):
        return {**deepcopy(self.manifest), "records": records}

    def test_empty_store_keeps_unknown_and_exact_context(self):
        body = self.client.get(f"/players/{self.player.id}/research", params={"prop_id": self.prop.id}).json()
        self.assertEqual(body["rest_workload"]["verified"]["status"], "unknown")
        self.assertEqual(body["selected_prop"]["id"], self.prop.id)
        self.assertEqual(body["selected_prop"]["event_id"], self.event.id)
        self.assertIsNone(body["rest_workload"]["verified"]["confirmed_missed_games"])

    def test_persisted_evidence_populates_actual_api_without_writes_or_history_change(self):
        before = self.client.get(f"/players/{self.player.id}/research", params={"prop_id": self.prop.id}).json()
        self.persist()
        statements = []
        def observe(conn, cursor, statement, *args):
            statements.append(statement.lstrip().split()[0].upper())
        event.listen(self.engine, "before_cursor_execute", observe)
        try:
            response = self.client.get(f"/players/{self.player.id}/research", params={"prop_id": self.prop.id})
        finally:
            event.remove(self.engine, "before_cursor_execute", observe)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        verified = body["rest_workload"]["verified"]
        self.assertEqual(verified["status"], "confirmed")
        self.assertEqual(verified["confirmed_missed_games"], 2)
        self.assertTrue(verified["team_back_to_back"])
        self.assertEqual(verified["last_confirmed_appearance"]["gap_days"], 3)
        self.assertEqual(verified["last_completed_team_game"]["full_rest_days"], 0)
        self.assertFalse(set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"})
        for key in ("selected_prop", "history", "trends", "splits", "games", "selection_available"):
            if key == "selected_prop":
                # Response observation time advances independently of evidence.
                body[key].pop("evaluated_at", None)
                before[key].pop("evaluated_at", None)
            self.assertEqual(body[key], before[key])

    def test_replay_is_idempotent_and_keeps_original_observations(self):
        first = self.persist()
        count = self.count()
        second = self.persist()
        self.assertEqual(first["inserted"], 27)
        self.assertEqual((second["inserted"], second["duplicates"]), (0, 27))
        self.assertEqual(self.count(), count)

    def test_partial_coverage_lower_bound_unknown_and_uncovered_are_separate(self):
        self.persist()
        value = self.result(self.other)
        self.assertEqual(value["status"], "partial")
        self.assertIsNone(value["confirmed_missed_games"])
        self.assertEqual(value["partial_missed_games_lower_bound"], 1)
        self.assertEqual((value["unknown_participation_games"], value["uncovered_games"]), (1, 1))
        self.assertIsNone(value["team_back_to_back"])

    def test_complete_team_rest_can_prove_negative_back_to_back(self):
        self.persist()
        value = self.result(reference=self.later)
        self.assertFalse(value["team_back_to_back"])
        self.assertEqual(value["last_completed_team_game"]["gap_days"], 2)
        self.assertEqual(value["last_completed_team_game"]["full_rest_days"], 1)

    def test_missing_boxscore_player_is_not_dnp(self):
        manifest = deepcopy(self.manifest)
        manifest["records"] = [row for row in manifest["records"] if not
            (row["kind"] == "participation" and row.get("game_id") == "990002")]
        self.persist(manifest)
        value = self.result()
        self.assertIsNone(value["confirmed_missed_games"])
        self.assertEqual(value["partial_missed_games_lower_bound"], 1)
        self.assertEqual(value["uncovered_games"], 1)

    def test_dnp_without_complete_boxscore_becomes_unknown(self):
        manifest = deepcopy(self.manifest)
        manifest["records"] = [row for row in manifest["records"] if not
            (row["kind"] == "coverage" and row.get("game_id") == "990002")]
        self.persist(manifest)
        value = self.result()
        self.assertEqual(value["unknown_participation_games"], 1)
        self.assertIsNone(value["confirmed_missed_games"])

    def test_premature_boxscore_cannot_confirm_nonappearance(self):
        manifest = deepcopy(self.manifest)
        game = next(row for row in manifest["records"] if row["kind"] == "game" and row["game_id"] == "990002")
        score = next(row for row in manifest["records"] if row["kind"] == "coverage" and row.get("game_id") == "990002")
        score["observed_at"] = game["payload"]["game_at"]
        self.persist(manifest)
        value = self.result()
        self.assertEqual(value["unknown_participation_games"], 1)
        self.assertIsNone(value["confirmed_missed_games"])

    def test_changed_status_preserves_both_observations_and_withholds_exact_total(self):
        self.persist()
        game = deepcopy(next(row for row in self.manifest["records"] if row["kind"] == "game" and row["game_id"] == "990002"))
        game["payload"].update(status="unfinished", completed_at=None)
        report = self.persist(self.subset([game]))
        self.assertEqual(report["inserted"], 1)
        self.assertGreater(report["conflicts"], 0)
        self.assertIsNone(self.result()["confirmed_missed_games"])

    def test_postponed_game_is_not_completed_from_scheduled_time(self):
        manifest = deepcopy(self.manifest)
        game = next(row for row in manifest["records"] if row["kind"] == "game" and row["game_id"] == "990003")
        game["payload"].update(status="postponed", completed_at=None, game_at=None)
        manifest["records"] = [row for row in manifest["records"] if not
            (row.get("game_id") == "990003" and row["kind"] in {"participation", "coverage"})]
        self.persist(manifest)
        self.assertEqual(self.result()["confirmed_missed_games"], 1)
        self.assertFalse(self.result()["team_back_to_back"])

    def test_provider_athlete_identity_collision_is_preserved_and_quarantined(self):
        self.persist()
        row = deepcopy(next(row for row in self.manifest["records"] if row["kind"] == "athlete"))
        row["player_id"] = self.other.id
        self.assertGreater(self.persist(self.subset([row]))["conflicts"], 0)
        self.assertEqual(self.result()["status"], "unknown")

    def test_local_player_multiple_provider_identities_are_not_arbitrarily_chosen(self):
        self.persist()
        row = deepcopy(next(row for row in self.manifest["records"] if row["kind"] == "athlete"))
        row["identity"] = "another-athlete-id"
        self.persist(self.subset([row]))
        self.assertEqual(self.result()["status"], "unknown")

    def test_contradictory_schedule_coverage_withholds_exact_totals(self):
        self.persist()
        row = deepcopy(next(row for row in self.manifest["records"] if row["kind"] == "coverage" and row["payload"]["coverage_type"] == "schedule"))
        row["payload"].update(complete=False, reconciled=False)
        self.persist(self.subset([row]))
        self.assertIsNone(self.result()["confirmed_missed_games"])
        self.assertTrue(any("Conflicting schedule" in note for note in self.result()["notes"]))

    def test_changed_membership_end_does_not_reuse_old_open_interval(self):
        self.persist()
        row = deepcopy(next(row for row in self.manifest["records"] if row["kind"] == "membership" and row["player_id"] == self.player.id))
        row["payload"]["ends_at"] = (self.reference.replace(tzinfo=UTC) - timedelta(hours=1)).isoformat()
        self.persist(self.subset([row]))
        value = self.result()
        self.assertIsNone(value["context_team_id"])
        self.assertIsNone(value["confirmed_missed_games"])
        self.assertTrue(any("Conflicting dated membership" in note for note in value["notes"]))

    def test_coverage_gap_stays_partial(self):
        manifest = deepcopy(self.manifest)
        row = next(row for row in manifest["records"] if row["kind"] == "coverage" and row["payload"]["coverage_type"] == "schedule")
        row["payload"]["ends_at"] = (self.reference.replace(tzinfo=UTC) - timedelta(hours=1)).isoformat()
        self.persist(manifest)
        self.assertIsNone(self.result()["confirmed_missed_games"])

    def test_trade_uses_dated_membership_instead_of_current_player_team(self):
        manifest = deepcopy(self.manifest)
        manifest["records"] = [row for row in manifest["records"] if not (row.get("game_id") or "").startswith("99010")]
        member = next(row for row in manifest["records"] if row["kind"] == "membership" and row["player_id"] == self.player.id)
        game = next(row for row in manifest["records"] if row["kind"] == "game" and row["game_id"] == "990003")
        switch = (datetime.fromisoformat(game["payload"]["game_at"]) - timedelta(hours=1)).isoformat()
        member["payload"]["ends_at"] = switch
        new_member = deepcopy(member)
        new_member.update(identity="traded-membership", team_id="fixture-partial-team")
        new_member["payload"].update(starts_at=switch, ends_at=None)
        manifest["records"].append(new_member)
        game["payload"]["home_team_id"] = "fixture-partial-team"
        for row in manifest["records"]:
            if row.get("game_id") == "990003" and row["kind"] in {"participation", "coverage"}:
                row["team_id"] = "fixture-partial-team"
        coverage = next(row for row in manifest["records"] if row["kind"] == "coverage" and row["payload"]["coverage_type"] == "schedule")
        new_coverage = deepcopy(coverage)
        new_coverage.update(identity="traded-schedule", team_id="fixture-partial-team")
        # Include all known games for the new team during this interval.
        new_coverage["payload"].update(starts_at=switch, game_ids=["990003"])
        manifest["records"].append(new_coverage)
        coverage["payload"].update(ends_at=switch, game_ids=["990001", "990002"])
        self.persist(manifest)
        value = self.result()
        self.assertEqual(value["context_team_id"], "fixture-partial-team")
        self.assertEqual(value["last_confirmed_appearance"]["team_id"], "fixture-confirmed-team")
        self.assertEqual(value["confirmed_missed_games"], 2)

    def test_referenced_retained_games_must_match_explicit_scope(self):
        self.persist()
        scope = {**self.scope, "start_date": self.manifest["date_end"]}
        for kind in ("participation", "coverage"):
            row = deepcopy(next(row for row in self.manifest["records"] if row["kind"] == kind and row.get("game_id") == "990001"))
            manifest = {**self.subset([row]), "date_start": scope["start_date"]}
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "scope"):
                reconcile_fixture(self.db, manifest, **scope, now=self.now)
        self.assertEqual(self.count(), 27)

    def test_future_clock_retained_observation_withholds_exact_coverage(self):
        self.persist()
        self.db.add(NBAEvidenceRecord(kind="team", identity="future-team", source="synthetic_fixture",
            payload={"name": "future"}, observed_at=self.now + timedelta(days=1), fingerprint="f" * 64))
        self.db.commit()
        value = self.result()
        self.assertIsNone(value["confirmed_missed_games"])
        self.assertTrue(any("Future-clock" in note for note in value["notes"]))

    def test_scope_and_future_observation_rejection_are_atomic(self):
        for mutation in ("future", "date", "team"):
            manifest = deepcopy(self.manifest)
            if mutation == "future":
                manifest["records"][0]["observed_at"] = (self.now + timedelta(days=1)).isoformat()
            elif mutation == "date":
                game = next(row for row in manifest["records"] if row["kind"] == "game")
                game["payload"]["scheduled_at"] = "2000-01-01T00:00:00+00:00"
                game["payload"]["game_at"] = "2000-01-01T00:00:00+00:00"
            else:
                manifest["records"][0]["identity"] = "different-provider-team"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.persist(manifest)
            self.assertEqual(self.count(), 0)

    def test_failed_complete_reconciliation_writes_nothing(self):
        manifest = deepcopy(self.manifest)
        row = next(row for row in manifest["records"] if row["kind"] == "coverage" and row["payload"]["coverage_type"] == "schedule")
        row["payload"]["game_ids"] = row["payload"]["game_ids"][:-1]
        with self.assertRaises(ValueError):
            self.persist(manifest)
        self.assertEqual(self.count(), 0)

    def test_partial_response_cannot_assert_complete(self):
        manifest = deepcopy(self.manifest)
        row = next(row for row in manifest["records"] if row["kind"] == "coverage")
        row["payload"].update(complete=True, reconciled=False)
        with self.assertRaises(ValueError):
            self.persist(manifest)
        self.assertEqual(self.count(), 0)

    def test_write_requires_matching_dry_run_digest(self):
        with self.assertRaisesRegex(ValueError, "digest"):
            reconcile_fixture(self.db, self.manifest, **self.scope, now=self.now, write=True, expected_digest="wrong")
        self.assertEqual(self.count(), 0)

    def test_dry_run_never_writes(self):
        report = reconcile_fixture(self.db, self.manifest, **self.scope, now=self.now)
        self.assertFalse(report["write"])
        self.assertEqual(self.count(), 0)

    def test_mid_batch_database_failure_rolls_back_only_new_records(self):
        self.persist()
        records = [{"kind": "team", "identity": f"new-{n}", "payload": {"name": f"new {n}"},
                    "source": "synthetic_fixture", "observed_at": self.now.isoformat()} for n in range(2)]
        manifest = self.subset(records)
        digest = reconcile_fixture(None, manifest, **self.scope, now=self.now)["digest"]
        original = self.db.execute
        inserts = [0]
        def failing(statement, *args, **kwargs):
            if getattr(statement, "is_insert", False):
                inserts[0] += 1
                if inserts[0] == 2:
                    return original(text("SELECT * FROM missing_reconciliation_rollback_probe"))
            return original(statement, *args, **kwargs)
        with patch.object(self.db, "execute", side_effect=failing), self.assertRaises(Exception):
            reconcile_fixture(self.db, manifest, **self.scope, now=self.now, write=True, expected_digest=digest)
        self.assertEqual(self.count(), 27)
        self.assertEqual(self.result()["confirmed_missed_games"], 2)


class NBAEvidenceSqliteTests(EvidenceScenarios, unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine, tables=[model.__table__ for model in
            (Player, Event, Prop, PropBook, PropBookSnapshot, PlayerGameLog, NBAEvidenceRecord)])
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.fixture()


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Disposable PostgreSQL URL required")
class NBAEvidenceServicePostgresTests(EvidenceScenarios, unittest.TestCase):
    def setUp(self):
        cls = pg_fixture.EventMigrationPostgresTests
        cls.setUpClass()
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.upgrade()
        self.engine = fixture.engine
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.fixture()


class FixtureTargetGuardTests(unittest.TestCase):
    def session(self, url="postgresql://fixture@127.0.0.1:59999/proppulse_test_guard"):
        db = MagicMock()
        db.get_bind.return_value.url = make_url(url)
        self.params = {"host": "127.0.0.1", "port": "59999", "dbname": "proppulse_test_guard", "user": "fixture"}
        db.connection.return_value.connection.driver_connection.get_dsn_parameters.return_value = self.params
        return db

    def test_ambient_libpq_rejected_before_connection(self):
        for key in ("PGHOSTADDR", "PGSERVICE", "PGDATABASE", "PGOPTIONS", "PGPORT"):
            db = self.session()
            with self.subTest(key=key), patch.dict(os.environ, {key: "unapproved"}), self.assertRaisesRegex(ValueError, "Ambient"):
                _test_target(db)
            db.connection.assert_not_called()
            db.query.assert_not_called()

    def test_effective_connection_must_match_url_before_any_query(self):
        for key, value in (("host", "unapproved"), ("hostaddr", "203.0.113.1"), ("port", "5432"),
                           ("dbname", "unapproved"), ("user", "other"), ("service", "redirect"), ("options", "-c session_replication_role=replica")):
            db = self.session()
            self.params[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Connected"):
                _test_target(db)
            db.query.assert_not_called()
            db.execute.assert_not_called()

    def test_unapproved_urls_rejected_without_connection(self):
        for url in ("postgresql://fixture@remote/proppulse_test_guard", "postgresql://fixture@127.0.0.1/development",
                    "postgresql://fixture@127.0.0.1/proppulse_test_guard?hostaddr=203.0.113.1",
                    "sqlite:///fixture.db", "sqlite:///:memory:?uri=true"):
            db = self.session(url)
            with self.subTest(url=url), self.assertRaises(ValueError):
                _test_target(db)
            db.connection.assert_not_called()


class FixtureCliTests(unittest.TestCase):
    def test_dry_run_never_connects_to_configured_database(self):
        from uuid import uuid4
        now = datetime.now(UTC)
        manifest, _, _ = participation_manifest(now, confirmed_player_id=str(uuid4()), partial_player_id=str(uuid4()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "internal_fixture.json"
            path.write_text(json.dumps(manifest))
            result = subprocess.run([sys.executable, "scripts/reconcile_nba_evidence.py", "--fixture", str(path),
                "--sport", "NBA", "--start-date", manifest["date_start"], "--end-date", manifest["date_end"],
                *[value for team in manifest["team_ids"] for value in ("--team-id", team)]],
                env={**os.environ, "DATABASE_URL": "postgresql://invalid@127.0.0.1:1/must_not_connect"},
                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["database_checked"])
        self.assertEqual(report["provider_http_attempts"], 0)
