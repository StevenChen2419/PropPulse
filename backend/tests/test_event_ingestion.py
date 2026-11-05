"""Event/offer regression scenarios on SQLite and opt-in disposable PostgreSQL.

External HTTP is blocked for every test. No app lifespan or configured DB used.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Event, Player, Prop, PropBook, PropBookSnapshot
from app.services.event_persistence import (upsert_event, EventConflict, provider_metadata,
    resolve_prop, event_report, finish_event_report)
from app.services.offer_service import offer_availability
from scripts import fetch_odds as ingestion
import test_ingestion_postgres as pg_fixture
from test_milestone2_ingestion import NBA, event, payload, parsed, START, OBSERVED


class EventScenarios:
    def metadata(self, **changes):
        return {**provider_metadata(event(), NBA), **changes}

    def player(self):
        result = Player(name="Test Player", team="Home Team", team_abbr="HOM", sport="NBA")
        self.db.add(result)
        self.db.flush()
        return result

    def apply(self, rows=None, **kwargs):
        status = ingestion.make_sport_status(NBA)
        result = ingestion.apply_updates_for_sport(self.db, NBA, parsed() if rows is None else rows,
                                                   status, **kwargs)
        self.db.commit()
        finish_event_report(status["event_relationships"], "committed")
        return result, status

    def bootstrap(self):
        self.player()
        self.apply()
        return self.db.query(Prop).one(), self.db.query(Event).one()

    def test_first_repeat_stable_uuid_and_price_change_only_history(self):
        prop, first = self.bootstrap()
        ids = prop.id, first.id, self.db.query(PropBook).one().id
        _, status = self.apply()
        self.assertEqual((prop.id, self.db.query(Event).one().id, self.db.query(PropBook).one().id), ids)
        self.assertEqual(prop.event_id, first.id)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)
        self.assertEqual(status["event_relationships"]["committed"]["events_reused"], 1)
        self.assertEqual(status["event_relationships"]["committed"]["existing_links_reused"], 1)

    def test_namespaces_keep_same_opaque_id_distinct(self):
        events = [upsert_event(self.db, self.metadata(**changes))[0] for changes in
                  ({}, {"provider": "other_provider"}, {"sport_key": "baseball_mlb"})]
        self.assertEqual(len({e.id for e in events}), 3)
        self.assertEqual({e.provider_event_id for e in events}, {"event-1"})

    def test_opaque_identity_is_not_stripped_or_lowercased(self):
        first, _ = upsert_event(self.db, self.metadata(provider_event_id=" Case/ID:42 "))
        second, _ = upsert_event(self.db, self.metadata(provider_event_id="case/id:42"))
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.provider_event_id, " Case/ID:42 ")

    def test_invalid_metadata_rejected_before_insert(self):
        for changes in ({"home_team": "unknown"}, {"away_team": " Home Team "},
                        {"scheduled_start_at": None}, {"home_team": "Bad\x00Team"},
                        {"sport_key": "not_a_sport"}, {"provider_event_id": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                upsert_event(self.db, self.metadata(**changes))
        self.assertEqual(self.db.query(Event).count(), 0)

    def test_existing_verified_legacy_prop_retains_uuid_and_links(self):
        player = self.player()
        legacy = Prop(player_id=player.id, prop_type="points", line=20.5, game_time=START,
                      odds_event_id="event-1", odds_sport_key=NBA, opponent="Away Team", is_home=True)
        self.db.add(legacy)
        self.db.commit()
        before = legacy.id
        _, status = self.apply()
        self.assertEqual(self.db.query(Prop).one().id, before)
        self.assertIsNotNone(legacy.event_id)
        self.assertEqual(status["event_relationships"]["committed"]["props_newly_linked"], 1)

    def test_ambiguous_legacy_identity_never_uses_first_or_creates_duplicate(self):
        player = self.player()
        for _ in range(2):
            self.db.add(Prop(player_id=player.id, prop_type="points", line=20.5, game_time=START,
                             odds_event_id="event-1", odds_sport_key=NBA, opponent="Away Team"))
        self.db.commit()
        _, status = self.apply()
        self.assertEqual(self.db.query(Prop).count(), 2)
        self.assertEqual(self.db.query(PropBook).count(), 0)
        self.assertEqual(status["event_relationships"]["reasons"], {"ambiguous_legacy_identity": 1})

    def test_missing_legacy_identity_remains_unresolved(self):
        player = self.player()
        legacy = Prop(player_id=player.id, prop_type="points", line=20.5)
        self.db.add(legacy)
        self.db.commit()
        self.apply()
        self.assertIsNone(legacy.event_id)
        self.assertEqual(self.db.query(Prop).count(), 1)
        self.assertEqual(self.db.query(PropBook).count(), 0)

    def test_schedule_discrepancy_in_other_legacy_market_blocks_linkage(self):
        player = self.player()
        for market, start in (("points", START), ("rebounds", START + timedelta(seconds=3))):
            self.db.add(Prop(player_id=player.id, prop_type=market, line=20.5, game_time=start,
                             odds_event_id="event-1", odds_sport_key=NBA, opponent="Away Team"))
        self.db.commit()
        _, status = self.apply(scope={"event_id": "event-1", "prop_type": "points"})
        self.assertEqual(self.db.query(Prop).filter(Prop.event_id.is_not(None)).count(), 0)
        self.assertIn("legacy_schedule_or_sport_conflict", status["event_relationships"]["reasons"])

    def test_wrong_legacy_sport_and_participants_rejected(self):
        player = self.player()
        e, _ = upsert_event(self.db, self.metadata())
        prop = Prop(player_id=player.id, prop_type="points", line=20.5, odds_event_id="event-1",
                    odds_sport_key="baseball_mlb", game_time=START, opponent="Away Team")
        with self.assertRaisesRegex(EventConflict, "legacy_provider_identity_conflict"):
            resolve_prop([prop], player.id, "points", e)
        prop.odds_sport_key = NBA
        prop.is_home = True
        prop.opponent = "Other Team"
        with self.assertRaisesRegex(EventConflict, "legacy_participant_conflict"):
            resolve_prop([prop], player.id, "points", e)

    def test_known_link_reassignment_rejected(self):
        prop, first = self.bootstrap()
        second, _ = upsert_event(self.db, self.metadata(provider="other_provider"))
        with self.assertRaisesRegex(EventConflict, "known_event_reassignment"):
            resolve_prop([prop], prop.player_id, prop.prop_type, second)
        self.assertEqual(prop.event_id, first.id)

    def test_valid_event_retained_when_player_rejected(self):
        _, status = self.apply()
        self.assertEqual(self.db.query(Event).count(), 1)
        self.assertEqual(self.db.query(Prop).count(), 0)
        self.assertEqual(status["availability"], "unavailable")
        self.assertEqual(status["event_relationships"]["committed"]["events_created"], 1)

    def test_unknown_team_never_changes_event_participants(self):
        player = self.player()
        player.team = "UNK"
        self.apply()
        self.assertEqual(self.db.query(Prop).count(), 0)
        e = self.db.query(Event).one()
        self.assertEqual((e.home_team, e.away_team), ("Home Team", "Away Team"))

    def test_conflicting_observations_reject_entire_identity_before_mutation(self):
        self.player()
        self.apply([parsed()[0], {**parsed()[0], "home_team": "Different Team"}])
        self.assertEqual(self.db.query(Event).count(), 0)
        self.assertEqual(self.db.query(PropBook).count(), 0)

    def test_participant_correction_refused_even_with_expected_start(self):
        prop, e = self.bootstrap()
        with self.assertRaisesRegex(EventConflict, "event_participants_conflict"):
            upsert_event(self.db, self.metadata(home_team="Different Team"),
                         expected_start=START.isoformat() + "Z")
        self.assertEqual(e.home_team, "Home Team")
        self.assertEqual(prop.game_time, START)

    def test_unversioned_schedule_change_preserves_all_data(self):
        prop, e = self.bootstrap()
        before = e.id, prop.id, prop.game_time, self.db.query(PropBook).one().provider_observed_at
        result, status = self.apply([{**parsed()[0], "game_time": (START + timedelta(seconds=3)).isoformat() + "Z"}])
        self.assertEqual(result["sportsbook_offers_saved"], 0)
        self.assertEqual((e.id, prop.id, prop.game_time, self.db.query(PropBook).one().provider_observed_at), before)
        self.assertIn("unversioned_schedule_conflict", status["event_relationships"]["reasons"])

    def test_authorized_schedule_update_syncs_omitted_market_without_freshness(self):
        prop, e = self.bootstrap()
        omitted = Prop(player_id=prop.player_id, event=e, odds_event_id=e.provider_event_id,
                       odds_sport_key=NBA, prop_type="rebounds", line=5.5, game_time=START)
        self.db.add(omitted)
        self.db.commit()
        book = self.db.query(PropBook).one()
        before = book.id, book.line, book.over_odds, book.under_odds, book.provider_observed_at, book.ingested_at, book.updated_at
        new_start = OBSERVED - timedelta(minutes=1)
        metadata = self.metadata(scheduled_start_at=new_start.isoformat() + "Z")
        updated, action = upsert_event(self.db, metadata, expected_start=START.isoformat() + "Z")
        self.db.commit()
        self.assertEqual((updated.id, action), (e.id, "updated"))
        self.assertEqual((prop.game_time, omitted.game_time), (new_start, new_start))
        self.assertEqual((book.id, book.line, book.over_odds, book.under_odds, book.provider_observed_at, book.ingested_at, book.updated_at), before)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)
        self.assertFalse(offer_availability(prop, book.sportsbook, book.line, "over")["actionable"])

    def test_stale_compare_and_set_cannot_undo_verified_schedule(self):
        _, e = self.bootstrap()
        newer = START + timedelta(hours=1)
        upsert_event(self.db, self.metadata(scheduled_start_at=newer.isoformat() + "Z"),
                     expected_start=START.isoformat() + "Z")
        self.db.commit()
        with self.assertRaisesRegex(EventConflict, "stale_schedule_correction"):
            upsert_event(self.db, self.metadata(), expected_start=START.isoformat() + "Z")
        self.assertEqual(e.scheduled_start_at, newer)

    def test_schedule_update_and_all_links_roll_back_together(self):
        prop, e = self.bootstrap()
        upsert_event(self.db, self.metadata(scheduled_start_at=(START + timedelta(hours=1)).isoformat() + "Z"),
                     expected_start=START.isoformat() + "Z")
        self.db.rollback()
        self.assertEqual((e.scheduled_start_at, prop.game_time), (START, START))

    def test_event_creation_and_prop_links_roll_back_with_sport(self):
        self.player()
        self.db.commit()
        status = ingestion.make_sport_status(NBA)
        ingestion.apply_updates_for_sport(self.db, NBA, parsed(), status)
        self.db.flush()
        self.db.rollback()
        finish_event_report(status["event_relationships"], "rolled_back")
        report = status["event_relationships"]
        self.assertEqual(self.db.query(Event).count(), 0)
        self.assertEqual(self.db.query(Prop).count(), 0)
        self.assertEqual(report["committed"]["events_created"], 0)
        self.assertEqual(report["rolled_back"]["events_created"], 1)
        self.assertEqual(report["rolled_back"]["props_newly_linked"], 1)

    def test_empty_market_metadata_can_persist_without_an_actionable_game(self):
        status = ingestion.make_sport_status(NBA)
        status["_authoritative_events"] = [self.metadata()]
        ingestion.apply_updates_for_sport(self.db, NBA, [], status)
        self.db.commit()
        self.assertEqual(self.db.query(Event).count(), 1)
        self.assertEqual(self.db.query(Prop).count(), 0)
        self.assertEqual(status["availability"], "unavailable")

    def test_invalid_metadata_counts_event_once_not_once_per_offer(self):
        rows = [{**parsed()[0], "home_team": "UNK"} for _ in range(4)]
        _, status = self.apply(rows)
        report = status["event_relationships"]
        self.assertEqual((report["events_parsed"], report["events_rejected"], report["database_attempts"]), (1, 1, 0))
        self.assertEqual(status["unmatched_outcomes"], 4)

    def test_schedule_correction_ingestion_reports_update_with_omitted_props(self):
        prop, e = self.bootstrap()
        other = Prop(player_id=prop.player_id, event=e, odds_event_id=e.provider_event_id,
                     odds_sport_key=NBA, prop_type="rebounds", line=5.5, game_time=START)
        self.db.add(other)
        self.db.commit()
        new_start = START + timedelta(minutes=10)
        result, status = self.apply([{**parsed()[0], "game_time": new_start.isoformat() + "Z"}],
            schedule_corrections={e.provider_event_id: START.isoformat() + "Z"},
            scope={"event_id": e.provider_event_id, "prop_type": "points"})
        counts = status["event_relationships"]["committed"]
        self.assertEqual((counts["events_updated"], counts["schedule_changes"]), (1, 1))
        self.assertEqual((prop.game_time, other.game_time), (new_start, new_start))
        self.assertEqual(result["sportsbook_snapshots_saved"], 0)

    def test_sport_commit_failure_clears_event_success_counts(self):
        self.player()
        self.db.commit()
        factory = sessionmaker(bind=self.db.get_bind())
        failing = factory()
        status = ingestion.make_sport_status(NBA)
        with patch.object(ingestion, "SPORT_CONFIG", {NBA: ingestion.SPORT_CONFIG[NBA]}), \
             patch.object(ingestion, "SessionLocal", return_value=failing), \
             patch.object(failing, "commit", side_effect=RuntimeError("isolated failure")):
            ingestion.persist_sports({NBA: status}, {NBA: parsed()}, {})
        self.assertEqual(status["outcome"], "failed")
        self.assertEqual(status["event_relationships"]["committed"]["events_created"], 0)
        self.assertEqual(status["event_relationships"]["rolled_back"]["events_created"], 1)
        self.assertEqual(self.db.query(Event).count(), 0)

    def test_parser_rejects_missing_participants_and_discovery_disagreement(self):
        from app.services.odds_parser import parse_event
        for change in ({"home_team": None}, {"away_team": "UNK"},
                       {"commence_time": START.isoformat()}, {"away_team": "Other Team"}):
            rows, issues = parse_event({**payload(), **change}, event(), NBA,
                                      ingestion.SPORT_CONFIG[NBA], OBSERVED)
            self.assertEqual(rows, [])
            self.assertTrue(issues)


class EventIngestionSQLiteTests(EventScenarios, unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[m.__table__ for m in (Event, Player, Prop, PropBook, PropBookSnapshot)])
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.addCleanup(patch.stopall)
        patch("builtins.print").start()
        patch("httpx.Client.send", side_effect=AssertionError("provider HTTP forbidden")).start()


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit isolated PostgreSQL URL unset")
class EventIngestionPostgresTests(EventScenarios, unittest.TestCase):
    setUpClass = classmethod(pg_fixture.IngestionPostgresTests.setUpClass.__func__)
    remove_schema = pg_fixture.IngestionPostgresTests.remove_schema

    def setUp(self):
        pg_fixture.IngestionPostgresTests.setUp(self)
        Base.metadata.create_all(self.engine)
        # Include the real identity trigger/constraints from the existing revision.
        pg_fixture.IngestionPostgresTests.upgrade_isolated_schema(self)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.addCleanup(patch.stopall)
        patch("builtins.print").start()
        patch("httpx.Client.send", side_effect=AssertionError("provider HTTP forbidden")).start()

    def test_concurrent_identity_inserts_reuse_one_uuid(self):
        barrier = threading.Barrier(2)
        def ingest():
            with self.Session.begin() as session:
                barrier.wait(timeout=10)
                e, action = upsert_event(session, self.metadata())
                return e.id, action
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: ingest(), range(2)))
        self.assertEqual(len({result[0] for result in results}), 1)
        self.assertEqual({result[1] for result in results}, {"created", "reused"})
        self.assertEqual(self.db.query(Event).count(), 1)

    def test_concurrent_schedule_corrections_cannot_overwrite_each_other(self):
        prop, first = self.bootstrap()
        barrier = threading.Barrier(2)
        def correct(hours):
            with self.Session.begin() as session:
                barrier.wait(timeout=10)
                try:
                    _, action = upsert_event(session,
                        self.metadata(scheduled_start_at=(START + timedelta(hours=hours)).isoformat() + "Z"),
                        expected_start=START.isoformat() + "Z")
                    return action
                except EventConflict as error:
                    return str(error)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(correct, (1, 2)))
        self.assertEqual(sorted(results), ["stale_schedule_correction", "updated"])
        self.db.expire_all()
        self.assertEqual(prop.game_time, first.scheduled_start_at)
        self.assertIn(prop.game_time, (START + timedelta(hours=1), START + timedelta(hours=2)))
