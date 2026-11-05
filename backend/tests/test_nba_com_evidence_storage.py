"""Offline namespace/crosswalk regressions; no provider or application database."""
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os
import unittest

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.database import Base
from app.models import NBAEvidenceRecord, Player
from app.services.nba_api_provider import verified_crosswalk
from app.services.nba_evidence_service import append_normalized_evidence, load_verified_evidence, reconcile_fixture
from participation_fixture import participation_manifest
import test_event_migration_postgres as pg_fixture

UTC = timezone.utc


class NBAComStorageScenarios:
    def fixture(self):
        self.now = datetime.now(UTC)
        self.player = Player(name="Exact UUID Fixture", team="Changed Team", team_abbr="WRG", sport="NBA")
        self.other = Player(name="Other UUID Fixture", team="Other", team_abbr="OTH", sport="NBA")
        self.db.add_all([self.player, self.other])
        self.db.flush()
        self.manifest, self.reference, _ = participation_manifest(self.now,
            confirmed_player_id=self.player.id, partial_player_id=self.other.id)
        self.crosswalk = self.review({"980001": self.player.id, "980002": self.other.id})
        self.scope = dict(sport="NBA", start_date=self.manifest["date_start"],
                          end_date=self.manifest["date_end"], team_ids=self.manifest["team_ids"])
        self.records = [deepcopy(row) for row in self.manifest["records"]
            if row["kind"] in {"team", "game", "athlete"}
            or row["kind"] == "participation" and row["payload"]["state"] == "appeared"]
        for row in self.records:
            row["source"] = "nba_api.stats.leaguegamelog" if row["kind"] in {"team", "game"} else "nba_api.stats.playergamelog"
            if row["kind"] == "game":
                payload = row["payload"]
                anchor = datetime.fromisoformat(payload["game_at"]).astimezone(ZoneInfo("America/New_York")).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()
                payload.update(time_precision="eastern_date", game_at=anchor, scheduled_at=anchor, completed_at=None)
        self.db.commit()

    def review(self, mapping, provenance="Reviewed synthetic UUID association"):
        return verified_crosswalk([dict(nba_player_id=athlete, player_id=local, verified=True,
                                       provenance=provenance) for athlete, local in mapping.items()])

    def append(self, records=None, **changes):
        kwargs = dict(provider="nba_com", crosswalk=self.crosswalk, now=self.now, **self.scope)
        kwargs.update(changes)
        return append_normalized_evidence(self.db, self.records if records is None else records, **kwargs)

    def persist(self, records=None):
        dry = self.append(records)
        return self.append(records, write=True, expected_digest=dry["digest"])

    def test_reviewed_append_idempotent_and_preserves_uuid(self):
        self.assertEqual(self.append()["inserted"], 0)
        inserted = self.persist()
        self.assertEqual(inserted["inserted"], len(self.records))
        again = self.persist()
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(again["duplicates"], len(self.records))
        self.assertEqual(set(self.db.scalars(select(NBAEvidenceRecord.player_id).where(
            NBAEvidenceRecord.player_id.is_not(None)))), {self.player.id, self.other.id})
        self.assertEqual(set(self.db.scalars(select(NBAEvidenceRecord.provider))), {"nba_com"})
        self.db.rollback()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(NBAEvidenceRecord)), 0)

    def test_espn_and_nba_com_same_raw_ids_remain_separate(self):
        dry = reconcile_fixture(self.db, self.manifest, now=self.now, **self.scope)
        reconcile_fixture(self.db, self.manifest, now=self.now, **self.scope,
                          write=True, expected_digest=dry["digest"])
        self.persist()
        evidence, notes = load_verified_evidence(self.db, self.player.id, now=self.now)
        self.assertEqual({item.provider for item in evidence.games}, {"espn", "nba_com"})
        self.assertIn("990001", {item.game_id for item in evidence.games})
        self.assertIn("nba_com:990001", {item.game_id for item in evidence.games})
        self.assertFalse(any("crosswalk" in note for note in notes))

    def test_unvalidated_live_records_rejected_and_retained_observations_quarantined(self):
        import hashlib
        import json
        records = deepcopy(self.manifest["records"])
        for row in records:
            row["source"] = "nba_api.live.boxscore"
        with self.assertRaisesRegex(ValueError, "unvalidated"):
            self.append(records)
        # Simulate previously retained rows by bypassing the new append boundary.
        for row in records:
            self.db.add(NBAEvidenceRecord(**{**row, "provider": "nba_com", "sport": "NBA",
                "observed_at": datetime.fromisoformat(row["observed_at"]),
                "fingerprint": hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()}))
        self.db.flush()
        evidence, notes = load_verified_evidence(self.db, self.player.id, now=self.now)
        self.assertEqual(evidence.games, ())
        self.assertEqual(evidence.participation, ())
        self.assertEqual(evidence.membership, ())
        self.assertEqual(evidence.coverage, ())
        self.assertTrue(any("unvalidated" in note for note in notes))

    def test_stats_cannot_assert_nonappearance_membership_or_complete_coverage(self):
        for kind in ("participation", "membership", "coverage"):
            row = deepcopy(next(row for row in self.manifest["records"] if row["kind"] == kind
                and (kind != "participation" or row["payload"]["state"] == "dnp")))
            row["source"] = "nba_api.stats.playergamelog"
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "Unsupported"):
                self.append([row])

    def test_plain_crosswalk_and_changed_review_provenance_cannot_bypass_review(self):
        with self.assertRaisesRegex(ValueError, "reviewed crosswalk"):
            self.append(crosswalk=dict(self.crosswalk))
        dry = self.append()
        changed = self.review(dict(self.crosswalk), provenance="Different reviewed association provenance")
        with self.assertRaisesRegex(ValueError, "digest"):
            self.append(crosswalk=changed, write=True, expected_digest=dry["digest"])
        with self.assertRaises(TypeError):
            self.crosswalk["980001"] = self.other.id

    def test_calendar_date_precision_preserved(self):
        records = deepcopy(self.records)
        for row in records:
            if row["kind"] == "game":
                payload = row["payload"]
                anchor = datetime.fromisoformat(payload["game_at"]).astimezone(ZoneInfo("America/New_York")).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()
                payload.update(time_precision="eastern_date", game_at=anchor, scheduled_at=anchor, completed_at=None)
        self.persist(records)
        evidence, _ = load_verified_evidence(self.db, self.player.id, now=self.now)
        self.assertEqual({item.time_precision for item in evidence.games}, {"eastern_date"})

    def test_date_only_precision_rejects_fabricated_actual_time(self):
        records = deepcopy(self.records)
        game = next(row for row in records if row["kind"] == "game")
        game["payload"]["game_at"] = game["payload"]["scheduled_at"] = self.now.replace(hour=12).isoformat()
        with self.assertRaisesRegex(ValueError, "calendar anchor"):
            self.append(records)

    def test_missing_ambiguous_or_wrong_crosswalk_rejected(self):
        for mapping in ({}, {"980001": self.other.id},
                        {"980001": self.player.id, "980002": self.player.id}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                self.append(crosswalk=mapping)

    def test_write_requires_matching_review_digest(self):
        with self.assertRaisesRegex(ValueError, "digest"):
            self.append(write=True, expected_digest="unreviewed")

    def test_unsupported_source_rejected(self):
        records = deepcopy(self.records)
        records[0]["source"] = "espn"
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.append(records)

    def test_conflicting_provider_crosswalk_excluded_without_affecting_other_provider(self):
        self.persist()
        rows = [deepcopy(row) for row in self.records if row["kind"] == "athlete" and row["identity"] == "980001"]
        rows[0]["player_id"] = self.other.id
        self.append(rows, crosswalk=self.review({"980001": self.other.id}), write=True,
                    expected_digest=self.append(rows, crosswalk=self.review({"980001": self.other.id}))["digest"])
        evidence, notes = load_verified_evidence(self.db, self.player.id, now=self.now)
        self.assertEqual(evidence.participation, ())
        self.assertTrue(any("crosswalk" in note for note in notes))


class NBAComStorageSQLiteTests(NBAComStorageScenarios, unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine, tables=[Player.__table__, NBAEvidenceRecord.__table__])
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.fixture()
        # SQLite legacy transaction mode needs an outer BEGIN before SAVEPOINT.
        self.db.connection().exec_driver_sql("BEGIN")


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit disposable PostgreSQL URL required")
class NBAComStoragePostgresTests(NBAComStorageScenarios, unittest.TestCase):
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
