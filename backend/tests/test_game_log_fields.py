import unittest
from datetime import datetime
from app.services.game_log_fields import espn_stats, number, provider_season


class GameLogFieldsTests(unittest.TestCase):
    def test_basketball_preserves_minutes_without_inventing_stats(self):
        for sport in ("NBA", "WNBA"):
            self.assertEqual(espn_stats(sport, ["minutes", "points"], ["32", "20"]),
                             {"minutes": 32, "points": 20})
            self.assertEqual(espn_stats(sport, ["minutes"], ["DNP"]), {})

    def test_hockey_converts_clock_time_to_minutes(self):
        self.assertAlmostEqual(espn_stats("NHL", ["timeOnIcePerGame"], ["24:49"])["time_on_ice"],
                               24 + 49 / 60)
        self.assertEqual(espn_stats("NHL", ["timeOnIcePerGame"], ["24:99"]), {})

    def test_football_retains_role_specific_activity_and_missing_snaps(self):
        stats = espn_stats("NFL", ["passingAttempts", "rushingAttempts"], ["28", "2"])
        self.assertEqual(stats, {"pass_attempts": 28, "rush_attempts": 2})
        self.assertNotIn("offensive_snaps", stats)
        self.assertNotIn("receptions", stats)

    def test_invalid_or_missing_is_not_zero(self):
        for value in (None, "--", "NaN", float("inf"), -1, True):
            self.assertIsNone(number(value))
        self.assertEqual(number("0"), 0)

    def test_negative_yardage_is_valid_but_negative_workload_is_not(self):
        self.assertEqual(espn_stats("NFL", ["rushingYards", "rushingAttempts"], ["-3", "-1"]),
                         {"rush_yds": -3})

    def test_league_season_rollovers(self):
        for sport in ("NBA", "NHL"):
            self.assertEqual(provider_season(sport, datetime(2026, 10, 1)), 2027)
            self.assertEqual(provider_season(sport, datetime(2026, 3, 1)), 2026)
            self.assertEqual(provider_season(sport, datetime(2026, 9, 30)), 2026)
        self.assertEqual(provider_season("NFL", datetime(2026, 1, 1)), 2025)
        self.assertEqual(provider_season("NFL", datetime(2026, 9, 1)), 2026)
        self.assertEqual(provider_season("WNBA", datetime(2026, 9, 1)), 2026)


if __name__ == "__main__":
    unittest.main()
