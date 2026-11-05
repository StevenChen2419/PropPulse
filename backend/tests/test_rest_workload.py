"""Synthetic arithmetic fixtures only; no application lifespan or provider HTTP."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from app.schemas import RestWorkloadOut
from app.services.rest_workload_service import build_rest_workload

UTC = timezone.utc


class RestWorkloadTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 10, 18, tzinfo=UTC)
        self.player = NS(id="player", sport="NBA")

    def log(self, days=1, minutes=30, **changes):
        date = changes.get("game_date", self.now - timedelta(days=days))
        return NS(**{"game_date": date, "sport": "NBA", "player_id": "player", "source": "espn_nba",
                     "external_game_id": str(date), "stats": {"minutes": minutes, "points": 20}, **changes})

    def build(self, logs, **kwargs):
        result = build_rest_workload(self.player, logs, now=self.now, **kwargs)
        RestWorkloadOut.model_validate(result)
        self.assertEqual(len(logs), result["coverage"]["eligible_games"] + sum(result["coverage"]["excluded_counts"].values()))
        return result

    def test_back_to_back(self):
        result = self.build([self.log()])
        self.assertEqual(result["rest"]["days_since_last_game"], 1)
        self.assertTrue(result["rest"]["back_to_back"])
        self.assertEqual(result["rest"]["category"], "back_to_back")

    def test_short_and_extended_rest(self):
        for days, expected in ((2, "short_rest"), (3, "extended_rest"), (12, "extended_rest")):
            self.assertEqual(self.build([self.log(days)])["rest"]["category"], expected)

    def test_eastern_midnight_boundary(self):
        self.now = datetime(2026, 11, 10, 5, 30, tzinfo=UTC)
        last = self.now - timedelta(hours=1)
        result = self.build([self.log(game_date=last, stats={"minutes": 20, "completed": True})])
        self.assertEqual(result["rest"]["days_since_last_game"], 1)

    def test_same_eastern_day_is_not_back_to_back(self):
        result = self.build([self.log(game_date=self.now - timedelta(hours=1), stats={"minutes": 20, "completed": True})])
        self.assertEqual(result["rest"]["days_since_last_game"], 0)
        self.assertFalse(result["rest"]["back_to_back"])
        self.assertIsNone(result["rest"]["category"])

    def test_offset_and_naive_utc_match(self):
        date = datetime(2026, 11, 9, 13, tzinfo=timezone(timedelta(hours=-5)))
        first = self.build([self.log(game_date=date)])
        second = self.build([self.log(game_date=date.astimezone(UTC).replace(tzinfo=None))])
        self.assertEqual(first["rest"], second["rest"])

    def test_rolling_7_14_inclusive_lower_boundary(self):
        result = self.build([self.log(n) for n in (1, 6, 7, 8, 13, 14, 15)])
        self.assertEqual(result["rest"]["games_in_7d"], 3)
        self.assertEqual(result["rest"]["games_in_14d"], 6)
        self.assertEqual(result["rest"]["schedule_density"], .429)

    def test_no_history_is_unknown_not_zero(self):
        result = self.build([])
        self.assertEqual(result["status"], "no_history")
        for key in ("days_since_last_game", "back_to_back", "games_in_7d", "games_in_14d"):
            self.assertIsNone(result["rest"][key])
        self.assertFalse(result["coverage"]["schedule_complete"])

    def test_authoritative_event_overrides_conflicting_legacy(self):
        event = NS(id="event", scheduled_start_at=self.now + timedelta(days=1))
        prop = NS(id="exact", event=event, game_time=self.now + timedelta(days=99))
        result = self.build([self.log()], prop=prop)
        self.assertEqual(result["reference"]["prop_id"], "exact")
        self.assertEqual(result["reference"]["source"], "event")
        self.assertEqual(result["rest"]["days_since_last_game"], 2)

    def test_legacy_dates_are_not_verified_schedule(self):
        prop = NS(id="exact", event=None, game_time=self.now + timedelta(days=99))
        result = self.build([self.log()], prop=prop)
        self.assertEqual(result["reference"]["source"], "as_of")
        self.assertEqual(result["rest"]["days_since_last_game"], 1)
        self.assertTrue(any("legacy" in note for note in result["coverage"]["notes"]))

    def test_future_and_same_day_unconfirmed_excluded(self):
        logs = [self.log(0), self.log(-1), self.log(game_date=self.now - timedelta(hours=1))]
        result = self.build(logs)
        self.assertEqual(result["coverage"]["excluded_counts"], {"future_game": 2, "completion_unknown_today": 1})

    def test_explicit_completed_today_allowed(self):
        result = self.build([self.log(game_date=self.now - timedelta(hours=1), stats={"minutes": 20, "completed": True})])
        self.assertEqual(result["coverage"]["eligible_games"], 1)

    def test_past_event_cuts_off_later_logs(self):
        result = self.build([self.log(1), self.log(3)], event=NS(id="e", scheduled_start_at=self.now - timedelta(days=2)))
        self.assertEqual(result["coverage"]["eligible_games"], 1)
        self.assertEqual(result["coverage"]["excluded_counts"], {"at_or_after_reference": 1})

    def test_l5_l10_arithmetic_and_variability(self):
        result = self.build([self.log(n, n * 2) for n in range(1, 11)])
        self.assertEqual(result["workload"]["l5"]["average_minutes"], 6)
        self.assertEqual(result["workload"]["l10"]["average_minutes"], 11)
        self.assertEqual(result["workload"]["minutes_trend"], -10)
        self.assertEqual(result["workload"]["variability"], 5.74)

    def test_cross_season_baseline_independent(self):
        recent = self.log(1, 40)
        previous = self.log(minutes=10, game_date=datetime(2026, 5, 1, tzinfo=UTC))
        result = self.build([recent, previous])
        self.assertEqual(result["workload"]["l5"]["average_minutes"], 25)
        self.assertEqual(result["workload"]["l5"]["seasons"], [2026, 2027])
        self.assertEqual(result["workload"]["season"]["average_minutes"], 40)
        self.assertEqual(result["workload"]["l5_vs_season"], -15)
        self.assertEqual(sum(split["games"] for split in result["rest_splits"]), 0)

    def test_no_current_season_baseline(self):
        result = self.build([self.log(game_date=datetime(2026, 5, 1, tzinfo=UTC))])
        self.assertIsNone(result["workload"]["season"]["average_minutes"])
        self.assertIsNone(result["workload"]["l5_vs_season"])

    def test_missing_minutes_not_replaced_in_window(self):
        result = self.build([self.log(n, None if n == 1 else n) for n in range(1, 7)])
        window = result["workload"]["l5"]
        self.assertEqual((window["games"], window["observed_games"], window["average_minutes"]), (4, 5, 3.5))
        self.assertEqual(result["workload"]["missing_minutes"], 1)
        self.assertTrue(window["insufficient_sample"])

    def test_unknown_workload_and_small_sample(self):
        result = self.build([self.log(minutes=None)])
        self.assertIsNone(result["workload"]["l5"]["average_minutes"])
        self.assertIsNone(result["workload"]["variability"])
        self.assertIsNone(result["workload"]["minutes_trend"])

    def test_invalid_minutes_remain_missing(self):
        for value in ("bad", -3, True, float("nan"), 101):
            result = self.build([self.log(minutes=value)])
            self.assertIsNone(result["workload"]["l5"]["average_minutes"])

    def test_invalid_minutes_only_do_not_establish_appearance(self):
        result = self.build([self.log(stats={"minutes": 101})])
        self.assertEqual(result["coverage"]["excluded_counts"], {"no_observed_statistics": 1})

    def test_wrong_sport_event_not_authoritative(self):
        event = NS(id="wrong", sport_key="baseball_mlb", scheduled_start_at=self.now + timedelta(days=3))
        result = self.build([self.log()], event=event)
        self.assertEqual(result["reference"]["source"], "as_of")
        self.assertIsNone(result["reference"]["event_id"])

    def test_duration_minutes(self):
        result = self.build([self.log(minutes="32:30")])
        self.assertEqual(result["workload"]["l5"]["average_minutes"], 32.5)

    def test_duplicates_count_once(self):
        log = self.log()
        result = self.build([log, log])
        self.assertEqual(result["coverage"]["excluded_counts"], {"duplicate_game": 1})
        self.assertEqual(result["rest"]["games_in_7d"], 1)

    def test_conflicting_duplicate_excludes_both(self):
        result = self.build([self.log(), self.log(minutes=40)])
        self.assertEqual(result["coverage"]["excluded_counts"], {"conflicting_game_logs": 2})

    def test_conflicting_id_dates_excludes_both(self):
        result = self.build([self.log(external_game_id="same"), self.log(2, external_game_id="same")])
        self.assertEqual(result["coverage"]["excluded_counts"], {"conflicting_game_logs": 2})

    def test_ineligible_duplicate_does_not_poison_valid(self):
        result = self.build([self.log(), self.log(minutes=20, player_id="other")])
        self.assertEqual(result["coverage"]["eligible_games"], 1)
        self.assertEqual(result["coverage"]["excluded_counts"], {"player_mismatch": 1})

    def test_unsupported_and_synthetic_inputs(self):
        for changes, reason in (({"source": "synthetic"}, "unsupported_source"),
                                ({"external_game_id": "synthetic-1"}, "synthetic_identity"),
                                ({"sport": "WNBA"}, "sport_mismatch"),
                                ({"game_date": None}, "invalid_date"),
                                ({"external_game_id": None}, "missing_game_identity"),
                                ({"stats": {}}, "no_observed_statistics"),
                                ({"stats": {"minutes": 0}}, "did_not_play"),
                                ({"stats": {"completed": False, "minutes": 30}}, "not_completed"),
                                ({"stats": {"season_type": "Pre-season", "minutes": 30}}, "preseason")):
            self.assertEqual(self.build([self.log(**changes)])["coverage"]["excluded_counts"], {reason: 1})

    def test_splits_have_independent_denominators(self):
        result = self.build([self.log(1, None), self.log(2, 30), self.log(4, 40), self.log(8, 20)])
        splits = {item["category"]: item for item in result["rest_splits"]}
        self.assertEqual((splits["back_to_back"]["games"], splits["back_to_back"]["minutes_games"]), (1, 0))
        self.assertEqual(splits["back_to_back"]["average_points"], 20)
        self.assertEqual(splits["short_rest"]["average_minutes"], 30)
        self.assertEqual(splits["extended_rest"]["average_minutes"], 40)

    def test_other_sports_explicitly_unavailable(self):
        self.player.sport = "MLB"
        result = self.build([self.log()])
        self.assertEqual(result["status"], "unsupported_sport")
        self.assertFalse(result["interpretation"]["experimental_model_used"])
