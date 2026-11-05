"""Mocked NBA dictionaries and disposable stores only; no NBA/ESPN requests."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import os
import importlib.util
from pathlib import Path
from uuid import uuid4
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Player, Event, Prop, PropBook, PropBookSnapshot, PlayerGameLog, NBAEvidenceRecord
from app.routers.players import router
from app.services.nba_api_provider import (
    nba_id, verified_crosswalk, normalize_team_games, normalize_player_games, normalize_live_boxscore,
    _inspect_live_boxscore_candidates,
)
from app.services.nba_evidence_service import append_normalized_evidence, load_verified_evidence
from app.services.rest_workload_service import build_verified_rest, VerifiedRestEvidence, MembershipEvidence
import test_event_migration_postgres as pg_fixture

UTC = timezone.utc
OBSERVED = datetime(2021, 1, 18, 12, tzinfo=UTC)
REFERENCE = datetime(2021, 1, 19, 0, tzinfo=UTC)  # Eastern Jan 18
NOW = datetime(2021, 1, 19, 12, tzinfo=UTC)
BOS, ORL = "1610612738", "1610612753"
ATHLETE = "1627759"  # Bundled NBA identity: Brown; local UUID below is a fixture.


def result_set(name, rows):
    headers = list(rows[0]) if rows else []
    return {"resultSets": [{"name": name, "headers": headers, "rowSet": [list(r.values()) for r in rows]}]}


def team_payload():
    rows = []
    for game, date in [("0022000180", "JAN 15, 2021"), ("0022000181", "JAN 17, 2021")]:
        for team, matchup, wl, points in [(BOS, "BOS vs. ORL", "W", 100), (ORL, "ORL @ BOS", "L", 90)]:
            rows.append(dict(TEAM_ID=int(team), GAME_ID=game, GAME_DATE=date, MATCHUP=matchup, WL=wl, PTS=points))
    return result_set("LeagueGameLog", rows)


def player_payload(minutes=25, points=0):
    return result_set("PlayerGameLog", [dict(Player_ID=int(ATHLETE), Game_ID="0022000180",
        GAME_DATE="JAN 15, 2021", MATCHUP="BOS vs. ORL", MIN=minutes, PTS=points)])


def live_payload(played="1", status="ACTIVE", reason=None, statistics=None):
    player = dict(personId=int(ATHLETE), played=played, status=status,
                  statistics={"points": 0} if statistics is None else statistics)
    if reason is not None:
        player["notPlayingReason"] = reason
    return {"game": dict(gameId="0022000180", gameTimeUTC="2021-01-16T00:30:00Z",
        gameStatus=3, gameStatusText="Final", homeTeam=dict(teamId=int(BOS), players=[player]),
        awayTeam=dict(teamId=int(ORL), players=[]))}


class NBAProviderTests(unittest.TestCase):
    def setUp(self):
        self.local = str(uuid4())
        self.crosswalk = verified_crosswalk([dict(nba_player_id=ATHLETE, player_id=self.local,
            verified=True, provenance="Synthetic local association; nba_api static player identity")])

    def live(self, payload=None):
        return _inspect_live_boxscore_candidates(payload or live_payload(), observed_at=OBSERVED, crosswalk=self.crosswalk)

    def state(self, payload):
        rows = self.live(payload)["unvalidated_candidates"]
        return next((r["payload"]["state"] for r in rows if r["kind"] == "participation"), None)

    def test_public_live_parser_quarantines_all_synthetic_semantics(self):
        for payload in (live_payload(), live_payload("0", "ACTIVE", "DNP"),
                        live_payload("0", "INACTIVE"), {}):
            result = normalize_live_boxscore(payload, observed_at=OBSERVED, crosswalk=self.crosswalk)
            self.assertEqual(result["records"], [])
            self.assertIn("unvalidated", result["issues"][0])
        self.assertNotIn("records", self.live())

    def test_completed_game_and_explicit_zero_point_missing_minute_appearance(self):
        result = self.live()
        self.assertEqual(self.state(live_payload()), "appeared")
        game = next(r for r in result["unvalidated_candidates"] if r["kind"] == "game")
        self.assertEqual(game["payload"]["status"], "completed")
        self.assertIsNone(game["payload"]["completed_at"])
        self.assertFalse(any(r["kind"] in {"membership", "coverage"} for r in result["unvalidated_candidates"]))

    def test_unfinished_and_unrecognized_final_do_not_classify_participation(self):
        for code, text in [(2, "Q4"), (1, "Scheduled"), (3, "Postponed"), ("3", "Final")]:
            payload = live_payload()
            payload["game"].update(gameStatus=code, gameStatusText=text)
            self.assertIsNone(self.state(payload))

    def test_dnp_and_inactive_require_explicit_consistent_fields(self):
        self.assertEqual(self.state(live_payload("0", "ACTIVE", "DNP")), "dnp")
        self.assertEqual(self.state(live_payload("0", "INACTIVE", "INJURY")), "inactive")
        self.assertEqual(self.state(live_payload("0", "ACTIVE")), "unknown")
        self.assertEqual(self.state(live_payload("0", "ACTIVE", "OTHER")), "unknown")
        self.assertEqual(self.state(live_payload(0, "INACTIVE")), "unknown")

    def test_conflicting_played_status_reason_or_statistics_unknown(self):
        for payload in [live_payload("1", "INACTIVE"), live_payload("1", "ACTIVE", "DNP"),
                        live_payload("0", "INACTIVE", statistics={"points": 2}),
                        live_payload("0", "ACTIVE", "DNP", {"minutes": "PT00M01.00S"})]:
            self.assertEqual(self.state(payload), "unknown")
        for stats in [{"steals": 1}, {"blocks": 1}, {"turnovers": 1}, {"foulsPersonal": 1},
                      {"minutes": "invalid"}, {"points": "2"}, {"minutesCalculated": "PT01M00.00S"},
                      {"minutesCalculated": "invalid"}]:
            self.assertEqual(self.state(live_payload("0", "INACTIVE", statistics=stats)), "unknown")

    def test_missing_athlete_stays_missing_not_dnp(self):
        payload = live_payload()
        payload["game"]["homeTeam"]["players"] = []
        self.assertIsNone(self.state(payload))

    def test_duplicate_athlete_rejected(self):
        payload = live_payload()
        payload["game"]["awayTeam"]["players"] = deepcopy(payload["game"]["homeTeam"]["players"])
        with self.assertRaises(ValueError):
            self.live(payload)
        payload = live_payload()
        payload["game"]["homeTeam"]["players"][0]["statistics"] = []
        with self.assertRaises(ValueError):
            self.live(payload)

    def test_ids_normalized_and_invalid_ids_rejected(self):
        self.assertEqual(nba_id(22000180, game=True), "0022000180")
        self.assertEqual(nba_id("001627759"), ATHLETE)
        for value in [True, -1, 0, "abc", "nba_com:2544", "1.0", 2.0]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                nba_id(value)

    def test_crosswalk_never_uses_name_team_or_espn_identity(self):
        self.assertEqual(self.live()["unvalidated_candidates"][-1]["player_id"], self.local)
        self.assertFalse(any(r["kind"] == "participation" for r in normalize_live_boxscore(
            live_payload(), observed_at=OBSERVED, crosswalk={})["records"]))
        for entries in [[dict(nba_player_id=ATHLETE, player_id=self.local, verified=False, provenance="name")],
                        [dict(nba_player_id=ATHLETE, player_id=self.local, verified=True, provenance="review")]*2,
                        [dict(nba_player_id=a, player_id=self.local, verified=True, provenance="review") for a in (ATHLETE, "2544")]]:
            with self.assertRaises(ValueError):
                verified_crosswalk(entries)

    def test_team_results_pair_into_date_only_completed_games(self):
        games = normalize_team_games(team_payload(), observed_at=OBSERVED)
        self.assertEqual(games["issues"], [])
        self.assertFalse(games["schedule_complete"])
        rows = [r for r in games["records"] if r["kind"] == "game"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["payload"]["game_at"], "2021-01-15T05:00:00+00:00")
        self.assertEqual(rows[0]["payload"]["time_precision"], "eastern_date")

    def test_stats_zero_points_positive_minutes_appearance(self):
        games = normalize_team_games(team_payload(), observed_at=OBSERVED)["records"]
        rows = normalize_player_games(player_payload(), observed_at=OBSERVED,
            crosswalk=self.crosswalk, game_records=games)["records"]
        self.assertEqual(rows[-1]["payload"]["state"], "appeared")
        self.assertEqual(rows[-1]["player_id"], self.local)

    def test_stats_missing_zero_minutes_and_unmatched_game_unknown(self):
        games = normalize_team_games(team_payload(), observed_at=OBSERVED)["records"]
        for minutes, records, mapping in [(None, games, self.crosswalk), (0, games, self.crosswalk),
                                           (25, [], self.crosswalk), (25, games, {})]:
            result = normalize_player_games(player_payload(minutes), observed_at=OBSERVED,
                crosswalk=mapping, game_records=records)
            self.assertEqual(result["records"], [])
            self.assertTrue(result["issues"])

    def test_incomplete_conflicting_or_future_team_results_withheld(self):
        payloads = []
        for column, value in [("WL", "L"), ("PTS", 50), ("MATCHUP", "BOS @ ORL"), ("TEAM_ID", int(ORL)),
                              ("GAME_DATE", "JAN 19, 2021")]:
            payload = team_payload()
            headers = payload["resultSets"][0]["headers"]
            payload["resultSets"][0]["rowSet"][0][headers.index(column)] = value
            payloads.append(payload)
        missing = team_payload()
        missing["resultSets"][0]["rowSet"].pop(0)
        payloads.append(missing)
        for payload in payloads:
            result = normalize_team_games(payload, observed_at=OBSERVED)
            self.assertEqual(len([r for r in result["records"] if r["kind"] == "game"]), 1)
            self.assertTrue(result["issues"])

    def test_malformed_result_shapes_rejected(self):
        payload = player_payload()
        payload["resultSets"][0]["headers"].append("MIN")
        with self.assertRaises(ValueError):
            normalize_player_games(payload, observed_at=OBSERVED, crosswalk=self.crosswalk, game_records=[])
        with self.assertRaises(ValueError):
            normalize_team_games(team_payload(), observed_at=OBSERVED.replace(tzinfo=None))


class ProbeGuardTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "scripts" / "probe_nba_api.py"
        spec = importlib.util.spec_from_file_location("probe_nba_api_test", path)
        self.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.probe)

    def test_request_limits_timeout_redirects_spacing_and_no_extra_routes(self):
        from requests import Response
        response = Response()
        response.status_code = 200
        url = "https://stats.nba.com/stats/playergamelog"
        with self.probe.ProbeSession() as session, patch("requests.Session.get", return_value=response) as get, \
                patch.object(self.probe.time, "sleep") as sleep:
            for _ in range(3):
                session.get(url)
            self.assertEqual(get.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertTrue(all(call.kwargs["timeout"] == 10 and call.kwargs["allow_redirects"] is False for call in get.call_args_list))
            with self.assertRaises(ValueError):
                session.get(url)
            with self.assertRaises(ValueError):
                session.get("https://other.example/stats/playergamelog")
            self.assertEqual(get.call_count, 3)

    def test_failure_consumes_attempt_without_retry(self):
        from requests import Timeout
        with self.probe.ProbeSession() as session, patch("requests.Session.get", side_effect=Timeout) as get:
            with self.assertRaises(Timeout):
                session.get("https://stats.nba.com/stats/leaguegamelog")
            self.assertEqual((session.attempts, get.call_count), (1, 1))

    def test_redirect_rejected_without_following(self):
        from requests import Response
        response = Response()
        response.status_code = 302
        response.headers["Location"] = "https://unexpected.example/"
        with self.probe.ProbeSession() as session, patch("requests.Session.get", return_value=response) as get:
            with self.assertRaises(ValueError):
                session.get("https://stats.nba.com/stats/playergamelog")
            self.assertEqual(get.call_count, 1)


class ProviderStoreScenarios:
    def fixture(self):
        self.player = Player(name="Synthetic Brown UUID", team="Wrong Current Team", team_abbr="WRG", sport="NBA")
        self.db.add(self.player)
        self.db.flush()
        self.crosswalk = verified_crosswalk([dict(nba_player_id=ATHLETE, player_id=self.player.id,
            verified=True, provenance="Explicit synthetic reviewed UUID association")])
        self.event = Event(provider="the_odds_api", sport_key="basketball_nba", provider_event_id="fixture-odds",
            home_team="Unrelated label", away_team="Other label", scheduled_start_at=REFERENCE)
        self.db.add(self.event)
        self.db.flush()
        self.prop = Prop(player_id=self.player.id, event_id=self.event.id, prop_type="points", line=15.5,
                         is_active=False, game_time=REFERENCE)
        self.db.add(self.prop)
        self.db.commit()
        games = normalize_team_games(team_payload(), observed_at=OBSERVED)["records"]
        appearances = normalize_player_games(player_payload(), observed_at=OBSERVED,
            crosswalk=self.crosswalk, game_records=games)["records"]
        records = games + appearances
        self.scope = dict(provider="nba_com", crosswalk=self.crosswalk, sport="NBA",
            start_date="2021-01-15", end_date="2021-01-18", team_ids=[BOS, ORL], now=NOW)
        dry = append_normalized_evidence(self.db, records, **self.scope)
        append_normalized_evidence(self.db, records, **self.scope, write=True, expected_digest=dry["digest"])
        self.db.commit()

    def evidence(self):
        return load_verified_evidence(self.db, self.player.id, now=NOW)[0]

    def build(self, evidence=None):
        return build_verified_rest(self.player.id, reference=REFERENCE, now=NOW, evidence=evidence or self.evidence())

    def membership(self, team=BOS, start="2021-01-15T00:00:00+00:00", end=None):
        return MembershipEvidence(self.player.id, f"nba_com:{team}", datetime.fromisoformat(start),
            datetime.fromisoformat(end) if end else None, "reviewed_dated_membership_fixture", OBSERVED, provider="nba_com")

    def test_parser_to_persistence_to_calculator_and_incomplete_coverage(self):
        result = self.build()
        self.assertEqual(result["last_confirmed_appearance"]["gap_days"], 3)
        self.assertEqual(result["last_confirmed_appearance"]["full_rest_days"], 2)
        self.assertIsNone(result["last_completed_team_game"])
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["schedule_complete"])

    def test_team_b2b_and_player_team_rest_differ_with_supported_membership(self):
        result = self.build(replace(self.evidence(), membership=(self.membership(),)))
        self.assertEqual(result["last_completed_team_game"]["gap_days"], 1)
        self.assertEqual(result["last_completed_team_game"]["full_rest_days"], 0)
        self.assertTrue(result["team_back_to_back"])
        self.assertIsNone(result["confirmed_missed_games"])

    def test_trade_does_not_rewrite_previous_appearance(self):
        evidence = self.evidence()
        # Exact historical intervals supplied as reviewed fixtures, never inferred.
        result = self.build(replace(evidence, membership=(
            self.membership(end="2021-01-16T00:00:00+00:00"),
            self.membership(ORL, start="2021-01-16T00:00:00+00:00"))))
        self.assertEqual(result["last_confirmed_appearance"]["team_id"], f"nba_com:{BOS}")
        self.assertEqual(result["context_team_id"], f"nba_com:{ORL}")

    def test_same_player_date_across_providers_needs_verified_game_crosswalk(self):
        nba = self.evidence()
        appearance = next(game for game in nba.games if game.game_id == nba.participation[0].game_id)
        espn_game = replace(appearance, game_id="espn-game", home_team_id="espn-team",
                            away_team_id="espn-opponent", provider="espn")
        espn_part = replace(nba.participation[0], game_id="espn-game", team_id="espn-team", provider="espn")
        result = self.build(replace(nba, games=(*nba.games, espn_game), participation=(*nba.participation, espn_part)))
        self.assertIsNone(result["last_confirmed_appearance"])
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertGreater(result["evidence_counts"]["excluded_conflicts"], 0)

    def test_unvalidated_live_does_not_poison_supported_stats(self):
        before = self.build()
        for payload in (live_payload(), live_payload("0", "ACTIVE", "DNP"), live_payload("0", "INACTIVE")):
            result = normalize_live_boxscore(payload, observed_at=OBSERVED, crosswalk=self.crosswalk)
            self.assertEqual(result["records"], [])
            self.assertTrue(any("unvalidated" in issue for issue in result["issues"]))
        self.assertEqual(self.build(), before)

    def test_typed_same_nba_date_precision_reconciles_without_live_source(self):
        evidence = self.evidence()
        original = next(game for game in evidence.games if game.game_id == evidence.participation[0].game_id)
        precise = replace(original, game_at=datetime(2021, 1, 16, 0, 30, tzinfo=UTC),
                          time_precision="instant", source="reviewed_exact_time_fixture")
        result = self.build(replace(evidence, games=(*evidence.games, precise)))
        self.assertEqual(result["last_confirmed_appearance"]["time_precision"], "instant")
        self.assertEqual(result["evidence_counts"]["excluded_conflicts"], 0)

    def test_direct_typed_unvalidated_live_evidence_cannot_verify_metrics(self):
        evidence = self.evidence()
        unvalidated = replace(evidence,
            games=tuple(replace(game, source="nba_api.live.boxscore") for game in evidence.games),
            participation=tuple(replace(part, source="nba_api.live.boxscore") for part in evidence.participation))
        self.assertIsNone(self.build(unvalidated)["last_confirmed_appearance"])

    def test_exact_research_prop_event_uuids_preserved_with_no_http_or_writes(self):
        app = FastAPI()
        app.include_router(router, prefix="/players")
        app.dependency_overrides[get_db] = lambda: self.db
        statements = []
        def observe(conn, cursor, statement, *args):
            statements.append(statement.lstrip().split()[0].upper())
        event.listen(self.engine, "before_cursor_execute", observe)
        try:
            with patch("requests.sessions.Session.request", side_effect=AssertionError("No live provider")), TestClient(app) as client:
                response = client.get(f"/players/{self.player.id}/research", params={"prop_id": self.prop.id})
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["selected_prop"]["id"], self.prop.id)
                self.assertEqual(body["selected_prop"]["event_id"], self.event.id)
                rest = body["rest_workload"]["verified"]
                self.assertEqual(rest["last_confirmed_appearance"]["provider"], "nba_com")
                self.assertEqual(rest["last_confirmed_appearance"]["time_precision"], "eastern_date")
        finally:
            event.remove(self.engine, "before_cursor_execute", observe)
        self.assertFalse(set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"})


class ProviderStoreSQLiteTests(ProviderStoreScenarios, unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine, tables=[m.__table__ for m in
            (Player, Event, Prop, PropBook, PropBookSnapshot, PlayerGameLog, NBAEvidenceRecord)])
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.fixture()


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit disposable PostgreSQL required")
class ProviderStorePostgresTests(ProviderStoreScenarios, unittest.TestCase):
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
