"""Local normalized evidence fixtures, never claimed upstream provider payloads."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
import unittest

from app.schemas import VerifiedRestOut
from app.services.rest_workload_service import (
    GameEvidence, ParticipationEvidence, MembershipEvidence, ScheduleCoverageEvidence,
    VerifiedRestEvidence, build_verified_rest, build_rest_workload,
)

UTC = timezone.utc


class VerifiedRestTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 10, 18, tzinfo=UTC)
        self.reference = self.now
        self.player_id = "player"
        self.games = [self.game("appearance", 3), self.game("missed1", 2), self.game("missed2", 1)]
        self.participation = [self.part("appearance", "appeared"), self.part("missed1", "dnp"), self.part("missed2", "inactive")]
        self.membership = [MembershipEvidence("player", "A", self.now - timedelta(days=20), None, "membership_fixture", self.now)]
        self.coverage = [ScheduleCoverageEvidence("A", self.now - timedelta(days=20), self.now, True, "schedule_fixture", self.now)]

    def game(self, identity, days, team="A", **changes):
        at = self.now - timedelta(days=days)
        return GameEvidence(**{"game_id": identity, "home_team_id": team, "away_team_id": "Opponent",
            "game_at": at, "completed_at": at + timedelta(hours=2), "status": "completed",
            "source": "final_fixture", "observed_at": self.now, **changes})

    def part(self, identity, state, team="A", **changes):
        return ParticipationEvidence(**{"player_id": "player", "game_id": identity, "team_id": team,
                                       "state": state, "source": "boxscore_fixture", "observed_at": self.now, **changes})

    def build(self):
        evidence = VerifiedRestEvidence(tuple(self.games), tuple(self.participation), tuple(self.membership), tuple(self.coverage))
        result = build_verified_rest(self.player_id, reference=self.reference, now=self.now, evidence=evidence)
        VerifiedRestOut.model_validate(result)
        return result

    def test_two_missed_games_player_vs_team_rest(self):
        result = self.build()
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["last_confirmed_appearance"]["gap_days"], 3)
        self.assertEqual(result["last_confirmed_appearance"]["full_rest_days"], 2)
        self.assertEqual(result["last_completed_team_game"]["gap_days"], 1)
        self.assertEqual(result["last_completed_team_game"]["full_rest_days"], 0)
        self.assertTrue(result["team_back_to_back"])
        self.assertEqual((result["confirmed_missed_games"], result["dnp_games"], result["inactive_games"]), (2, 1, 1))

    def test_explicit_appearance_needs_no_minutes_or_points(self):
        # No points/minutes fields even exist on normalized participation. A
        # confirmed appearance with zero points or missing minutes is valid.
        result = self.build()
        self.assertEqual(result["last_confirmed_appearance"]["game_id"], "appearance")

    def test_existing_zero_point_log_does_not_promote_finality(self):
        log = NS(game_date=self.now - timedelta(days=1), stats={"points": 0}, sport="NBA",
                 source="espn_nba", external_game_id="old", player_id="player")
        result = build_rest_workload(NS(id="player", sport="NBA", team="A"), [log], now=self.now)
        self.assertEqual(result["coverage"]["eligible_games"], 1)
        self.assertEqual(result["verified"]["status"], "unknown")
        self.assertIsNone(result["verified"]["last_confirmed_appearance"])

    def test_old_log_completed_flag_alone_is_not_adapter(self):
        log = NS(game_date=self.now - timedelta(days=1), stats={"minutes": 30, "completed": True}, sport="NBA",
                 source="espn_nba", external_game_id="old", player_id="player")
        self.assertEqual(build_rest_workload(NS(id="player", sport="NBA"), [log], now=self.now)["verified"]["status"], "unknown")

    def test_unknown_default_has_no_zero_missed_claim(self):
        result = build_verified_rest("player", reference=self.now, now=self.now)
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertIsNone(result["partial_missed_games_lower_bound"])
        self.assertIsNone(result["team_back_to_back"])

    def test_wrapper_back_to_back_needs_authoritative_selected_game(self):
        evidence = VerifiedRestEvidence(tuple(self.games), tuple(self.participation), tuple(self.membership), tuple(self.coverage))
        self.assertTrue(self.build()["team_back_to_back"])
        player = NS(id="player", sport="NBA")
        as_of = build_rest_workload(player, [], now=self.now, verified_evidence=evidence)
        self.assertIsNone(as_of["verified"]["team_back_to_back"])
        event = NS(id="event", sport_key="basketball_nba", scheduled_start_at=self.now)
        selected = build_rest_workload(player, [], event=event, now=self.now, verified_evidence=evidence)
        self.assertTrue(selected["verified"]["team_back_to_back"])
        self.assertEqual(selected["reference"]["event_id"], "event")

    def test_missing_participation_not_dnp(self):
        self.participation = self.participation[:2]
        result = self.build()
        self.assertEqual(result["uncovered_games"], 1)
        self.assertEqual(result["partial_missed_games_lower_bound"], 1)
        self.assertIsNone(result["confirmed_missed_games"])

    def test_explicit_unknown_separate_from_uncovered(self):
        self.participation[2] = self.part("missed2", "unknown")
        result = self.build()
        self.assertEqual((result["unknown_participation_games"], result["uncovered_games"]), (1, 0))
        self.assertIsNone(result["confirmed_missed_games"])

    def test_incomplete_schedule_only_lower_bound(self):
        self.coverage = []
        result = self.build()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["partial_missed_games_lower_bound"], 2)
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertEqual(result["last_completed_team_game"]["status"], "partial")

    def test_incomplete_team_schedule_cannot_claim_no_b2b(self):
        self.games = self.games[:2]
        self.participation = self.participation[:2]
        self.coverage = []
        self.assertIsNone(self.build()["team_back_to_back"])

    def test_complete_team_schedule_can_claim_no_b2b(self):
        self.games = self.games[:2]
        self.participation = self.participation[:2]
        self.assertFalse(self.build()["team_back_to_back"])

    def test_trades_use_dated_membership_and_game_team(self):
        transfer = self.now - timedelta(days=2, hours=12)
        self.membership = [replace(self.membership[0], ends_at=transfer),
            MembershipEvidence("player", "B", transfer, None, "trade_fixture", self.now)]
        self.coverage = [replace(self.coverage[0], ends_at=transfer),
            ScheduleCoverageEvidence("B", transfer, self.now, True, "schedule_fixture", self.now)]
        self.games[1:] = [self.game("missed1", 2, "B"), self.game("missed2", 1, "B")]
        self.participation[1:] = [self.part("missed1", "dnp", "B"), self.part("missed2", "inactive", "B")]
        self.games.append(self.game("former-team", .5, "A"))
        result = self.build()
        self.assertEqual(result["context_team_id"], "B")
        self.assertEqual(result["last_confirmed_appearance"]["team_id"], "A")
        self.assertEqual(result["last_completed_team_game"]["game_id"], "missed2")
        self.assertEqual(result["confirmed_missed_games"], 2)

    def test_no_membership_never_uses_mutable_player_team(self):
        self.membership = []
        result = self.build()
        self.assertIsNone(result["context_team_id"])
        self.assertIsNone(result["last_completed_team_game"])
        self.assertEqual(result["partial_missed_games_lower_bound"], 2)
        self.assertIsNone(result["confirmed_missed_games"])

    def test_membership_gap_prevents_exact_count(self):
        self.membership = [replace(self.membership[0], starts_at=self.now - timedelta(days=2))]
        self.assertIsNone(self.build()["confirmed_missed_games"])

    def test_conflicting_membership_fails_closed(self):
        self.membership.append(replace(self.membership[0], team_id="B"))
        result = self.build()
        self.assertIsNone(result["context_team_id"])
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertGreater(result["evidence_counts"]["excluded_conflicts"], 0)

    def test_duplicate_identical_rows_count_once(self):
        self.games.append(self.games[1])
        self.participation.append(self.participation[1])
        self.assertEqual(self.build()["confirmed_missed_games"], 2)

    def test_conflicting_game_identity_excludes_all(self):
        self.games.append(replace(self.games[1], status="unfinished", completed_at=None))
        result = self.build()
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertGreater(result["evidence_counts"]["excluded_conflicts"], 0)

    def test_same_team_time_conflicting_game_ids_not_two_misses(self):
        self.games.append(replace(self.games[1], game_id="other-id"))
        self.participation.append(self.part("other-id", "dnp"))
        result = self.build()
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertEqual(result["partial_missed_games_lower_bound"], 1)
        self.assertGreater(result["evidence_counts"]["excluded_conflicts"], 0)

    def test_same_team_day_slightly_different_times_are_conflict(self):
        self.games.append(replace(self.games[1], game_id="slightly-different",
                                  game_at=self.games[1].game_at + timedelta(minutes=1)))
        self.participation.append(self.part("slightly-different", "dnp"))
        result = self.build()
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertGreater(result["evidence_counts"]["excluded_conflicts"], 0)

    def test_conflicting_participation_excludes_state(self):
        self.participation.append(self.part("missed1", "appeared"))
        result = self.build()
        self.assertEqual(result["last_confirmed_appearance"]["game_id"], "appearance")
        self.assertIsNone(result["confirmed_missed_games"])

    def test_postponed_cancelled_unfinished_games_excluded(self):
        for status in ("postponed", "cancelled", "unfinished", "unknown"):
            with self.subTest(status=status):
                original = self.games
                self.games = [self.games[0], replace(self.games[1], status=status, completed_at=None)]
                self.participation = self.participation[:1]
                result = self.build()
                self.assertEqual(result["confirmed_missed_games"], 0)
                self.assertEqual(result["last_completed_team_game"]["game_id"], "appearance")
                self.games = original

    def test_future_observation_not_evidence(self):
        self.participation[1] = replace(self.participation[1], observed_at=self.now + timedelta(seconds=1))
        result = self.build()
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertGreater(result["evidence_counts"]["excluded_invalid"], 0)

    def test_dnp_and_inactive_before_final_not_confirmed(self):
        for state in ("dnp", "inactive"):
            with self.subTest(state=state):
                self.participation[1] = self.part("missed1", state,
                    observed_at=self.games[1].game_at + timedelta(minutes=30))
                result = self.build()
                self.assertIsNone(result["confirmed_missed_games"])
                self.assertEqual(result["partial_missed_games_lower_bound"], 1)

    def test_no_completion_time_dnp_needs_final_observation(self):
        self.games[1] = replace(self.games[1], completed_at=None)
        self.participation[1] = self.part("missed1", "dnp", observed_at=self.games[1].game_at + timedelta(hours=4))
        self.assertIsNone(self.build()["confirmed_missed_games"])

    def test_appearance_before_final_is_positive_evidence(self):
        self.participation[0] = self.part("appearance", "appeared",
            observed_at=self.games[0].game_at + timedelta(minutes=30))
        self.assertEqual(self.build()["last_confirmed_appearance"]["game_id"], "appearance")

    def test_future_selected_reference_not_complete(self):
        self.reference = self.now + timedelta(days=1)
        result = self.build()
        self.assertFalse(result["schedule_complete"])
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertIsNone(result["team_back_to_back"])

    def test_future_interval_cannot_prove_completeness(self):
        self.coverage[0] = replace(self.coverage[0], ends_at=self.now + timedelta(days=1))
        result = self.build()
        self.assertIsNone(result["confirmed_missed_games"])
        self.assertFalse(result["schedule_complete"])

    def test_interval_observed_before_end_not_complete(self):
        self.coverage[0] = replace(self.coverage[0], observed_at=self.now - timedelta(hours=1))
        self.assertIsNone(self.build()["confirmed_missed_games"])

    def test_contiguous_coverage_intervals_union(self):
        split = self.now - timedelta(days=2)
        self.coverage = [replace(self.coverage[0], ends_at=split), replace(self.coverage[0], starts_at=split)]
        self.assertEqual(self.build()["confirmed_missed_games"], 2)

    def test_coverage_hole_not_complete(self):
        split = self.now - timedelta(days=2)
        self.coverage = [replace(self.coverage[0], ends_at=split - timedelta(seconds=1)), replace(self.coverage[0], starts_at=split)]
        self.assertIsNone(self.build()["confirmed_missed_games"])

    def test_no_appearance_baseline_withholds_missed_total(self):
        self.participation[0] = self.part("appearance", "dnp")
        result = self.build()
        self.assertIsNone(result["last_confirmed_appearance"])
        self.assertIsNone(result["partial_missed_games_lower_bound"])
        self.assertIsNone(result["confirmed_missed_games"])

    def test_historical_final_unknown_until_after_reference(self):
        self.reference = self.now - timedelta(days=2, hours=12)
        self.games = [replace(self.games[0], completed_at=None)]
        self.participation = self.participation[:1]
        result = self.build()
        self.assertIsNone(result["last_confirmed_appearance"])

    def test_historical_actual_completion_before_reference_allowed(self):
        self.reference = self.now - timedelta(days=2, hours=12)
        self.games = self.games[:1]
        self.participation = self.participation[:1]
        self.assertIsNotNone(self.build()["last_confirmed_appearance"])

    def test_finality_is_not_inferred_from_old_game_age(self):
        self.games = [replace(self.games[0], status="unknown", completed_at=None)]
        self.participation = self.participation[:1]
        self.assertIsNone(self.build()["last_confirmed_appearance"])

    def test_wrong_player_provider_sport_evidence_rejected(self):
        for changes in ({"player_id": "other"}, {"provider": "other"}, {"sport": "WNBA"}):
            with self.subTest(changes=changes):
                self.participation = [replace(self.part("appearance", "appeared"), **changes)]
                self.assertIsNone(self.build()["last_confirmed_appearance"])

    def test_missing_team_participation_cannot_prove_appearance(self):
        self.participation[0] = replace(self.participation[0], team_id="Not participant")
        self.assertIsNone(self.build()["last_confirmed_appearance"])

    def test_invalid_game_invalidates_exact_zero(self):
        self.games.append(self.game("invalid", -1))
        result = self.build()
        self.assertIsNone(result["confirmed_missed_games"])

    def test_eastern_calendar_and_full_days(self):
        self.games = [self.game("appearance", 3, game_at=datetime(2026, 11, 9, 4, 30, tzinfo=UTC),
                                completed_at=datetime(2026, 11, 9, 7, tzinfo=UTC))]
        self.participation = self.participation[:1]
        result = self.build()
        self.assertEqual(result["last_confirmed_appearance"]["gap_days"], 2)
        self.assertEqual(result["last_confirmed_appearance"]["full_rest_days"], 1)

    def test_offseason_long_gap_not_missing_games_assumption(self):
        self.games = [self.game("appearance", 180)]
        self.participation = self.participation[:1]
        self.membership[0] = replace(self.membership[0], starts_at=self.now - timedelta(days=190))
        self.coverage = []
        result = self.build()
        self.assertEqual(result["last_confirmed_appearance"]["gap_days"], 180)
        self.assertEqual(result["partial_missed_games_lower_bound"], 0)
        self.assertIsNone(result["confirmed_missed_games"])

    def test_provenance_observation_and_completion_kept_distinct(self):
        result = self.build()
        appearance = result["last_confirmed_appearance"]
        self.assertEqual(appearance["provider"], "espn")
        self.assertEqual(appearance["observed_at"], self.now.isoformat())
        self.assertNotEqual(appearance["completed_at"], appearance["observed_at"])
        self.assertEqual(appearance["participation_source"], "boxscore_fixture")

    def test_same_day_full_rest_days_never_negative(self):
        self.games = [self.game("appearance", .2)]
        self.participation = self.participation[:1]
        result = self.build()
        self.assertEqual(result["last_confirmed_appearance"]["full_rest_days"], 0)
