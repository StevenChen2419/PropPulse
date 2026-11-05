"""Synthetic repository-shape examples, never claimed as retained ESPN payloads."""
from copy import deepcopy
from datetime import datetime, timezone
import os
import unittest

from app.services.espn_nba_contract_adapter import audit_collected_response, VERSION
import test_nba_evidence_service as evidence_fixture


def envelope(endpoint="gamelog", payload=None, **values):
    return {"collection_version": 1, "endpoint": endpoint, "scope_id": "1001",
            "observed_at": "2026-10-17T12:00:00+00:00", "payload": payload or {}, **values}


def synthetic_gamelog(points="0", minutes="32"):
    return {"names": ["points", "minutes"], "events": {"9001": {"gameDate": "2026-10-16T23:00:00Z"}},
            "seasonTypes": [{"categories": [{"events": [{"eventId": "9001", "stats": [points, minutes]}]}]}]}


class ESPNContractAdapterTests(unittest.TestCase):
    def assert_unverified(self, result):
        self.assertEqual(result["adapter_version"], VERSION)
        self.assertFalse(result["safe_to_reconcile"])
        self.assertEqual(result["evidence_records"], [])
        self.assertTrue(all(value is None for value in result["verified"].values()))

    def test_zero_points_remains_observation_never_dnp(self):
        result = audit_collected_response(envelope(payload=synthetic_gamelog()))
        self.assert_unverified(result)
        self.assertEqual(result["candidates"][0]["provider_id"], "9001")
        self.assertIsNone(result["candidates"][0]["participation"])

    def test_missing_minutes_does_not_become_absence(self):
        result = audit_collected_response(envelope(payload=synthetic_gamelog("7", None)))
        self.assert_unverified(result)
        self.assertEqual(len(result["candidates"]), 1)

    def test_timezone_conversion_and_no_collection_time_as_game_time(self):
        payload = synthetic_gamelog()
        payload["events"]["9001"]["gameDate"] = "2026-10-16T20:00:00-04:00"
        result = audit_collected_response(envelope(payload=payload))
        self.assertEqual(result["candidates"][0]["game_at"], "2026-10-17T00:00:00+00:00")
        payload["events"].clear()
        result = audit_collected_response(envelope(payload=payload))
        self.assertIsNone(result["candidates"][0]["game_at"])

    def test_naive_game_date_is_unknown(self):
        payload = synthetic_gamelog()
        payload["events"]["9001"]["gameDate"] = "2026-10-16T20:00:00"
        self.assertIsNone(audit_collected_response(envelope(payload=payload))["candidates"][0]["game_at"])

    def test_mismatched_statistic_columns_are_reported(self):
        payload = synthetic_gamelog()
        payload["names"] = ["points"]
        self.assertFalse(audit_collected_response(envelope(payload=payload))["candidates"][0]["statistic_columns_match"])

    def test_duplicate_conflicting_observations_are_not_overwritten(self):
        payload = synthetic_gamelog()
        rows = payload["seasonTypes"][0]["categories"][0]["events"]
        rows.append({"eventId": "9001", "stats": ["40", "40"]})
        result = audit_collected_response(envelope(payload=payload))
        self.assertEqual(len(result["candidates"]), 2)
        self.assert_unverified(result)

    def test_missing_identity_is_not_generated_from_date_or_stats(self):
        payload = synthetic_gamelog()
        del payload["seasonTypes"][0]["categories"][0]["events"][0]["eventId"]
        self.assertEqual(audit_collected_response(envelope(payload=payload))["candidates"], [])

    def test_unverified_summary_scenarios_are_opaque(self):
        # These labels are internal test scenarios, NOT alleged ESPN fields.
        for scenario in ("final", "unfinished", "appeared", "zero_point_appearance", "missing_minute_appearance",
                         "dnp", "inactive", "omitted_player", "traded_player", "postponed", "cancelled",
                         "partial_response", "conflicting_statuses", "missing_identity"):
            with self.subTest(scenario=scenario):
                result = audit_collected_response(envelope("summary", {"internal_test_scenario": scenario}))
                self.assert_unverified(result)
                self.assertEqual(result["candidates"], [])

    def test_scoreboard_never_asserts_schedule_completeness(self):
        self.assert_unverified(audit_collected_response(envelope("scoreboard", {"internal_test_scenario": "full_day"})))

    def test_team_identity_shape_only(self):
        result = audit_collected_response(envelope("teams", {"sports": [{"leagues": [{"teams": [{"team": {"id": "12"}}]}]}]}))
        self.assertEqual(result["candidates"], [{"kind": "team_identity", "provider_id": "12"}])
        self.assert_unverified(result)

    def test_roster_changes_do_not_create_historical_membership(self):
        payload = {"athletes": [{"items": [{"id": "45"}]}]}
        left = audit_collected_response(envelope("roster", payload, scope_id="12"))
        right = audit_collected_response(envelope("roster", payload, scope_id="13"))
        for result in (left, right):
            self.assert_unverified(result)
            self.assertIsNone(result["candidates"][0]["historical_membership"])
        self.assertNotEqual(left["candidates"], right["candidates"])

    def test_missing_roster_player_is_not_synthesized(self):
        result = audit_collected_response(envelope("roster", {"athletes": []}))
        self.assertEqual(result["candidates"], [])
        self.assert_unverified(result)

    def test_athlete_pagination_always_remains_uncertain(self):
        for pages in (1, 4, None, True):
            with self.subTest(pages=pages):
                result = audit_collected_response(envelope("athletes", {"items": [{"id": "45"}], "pageCount": pages}))
                self.assertIsNone(result["pagination"]["complete"])
                self.assert_unverified(result)

    def test_partial_and_malformed_collections_remain_unknown(self):
        for payload in ({}, {"seasonTypes": [None]}, {"seasonTypes": "partial"}):
            self.assert_unverified(audit_collected_response(envelope(payload=payload)))

    def test_invalid_envelopes_and_nonfinite_json_rejected(self):
        for value in ({}, envelope(observed_at="2026-10-17"), envelope(collection_version=True),
                      envelope(endpoint=[]), envelope(payload={"value": float("nan")})):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                audit_collected_response(value)

    def test_determinism_input_preservation_and_no_raw_payload_echo(self):
        value = envelope(payload=synthetic_gamelog())
        before = deepcopy(value)
        first = audit_collected_response(value)
        self.assertEqual(first, audit_collected_response(value))
        self.assertEqual(value, before)
        self.assertNotIn("payload", first)
        self.assertEqual(first["observation_time_kind"], "collector_receipt_not_provider_update")


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit disposable PostgreSQL required")
class ESPNContractBridgePostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = evidence_fixture.NBAEvidenceServicePostgresTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_unverified_audit_keeps_persisted_research_unknown(self):
        result = audit_collected_response(envelope("summary", {"internal_test_scenario": "explicit_dnp"}))
        self.assertEqual(result["evidence_records"], [])
        self.assertFalse(result["safe_to_reconcile"])
        self.assertEqual(self.fixture.count(), 0)
        body = self.fixture.client.get(f"/players/{self.fixture.player.id}/research", params={"prop_id": self.fixture.prop.id}).json()
        self.assertEqual(body["rest_workload"]["verified"]["status"], "unknown")
        self.assertEqual(body["selected_prop"]["id"], self.fixture.prop.id)
        self.assertEqual(body["selected_prop"]["event_id"], self.fixture.event.id)

    def test_existing_six_kind_fixture_reconciliation_stays_separate_and_idempotent(self):
        self.fixture.persist()
        self.assertEqual(self.fixture.count(), 27)
        self.assertEqual(self.fixture.persist()["inserted"], 0)
        self.assertEqual(self.fixture.result()["confirmed_missed_games"], 2)
        result = audit_collected_response(envelope(payload=synthetic_gamelog("0", None)))
        self.assertEqual(result["evidence_records"], [])
        self.assertEqual(self.fixture.count(), 27)
