import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.trend_service import build_exact_line_trends, build_line_results


class ExactLineTrendTests(unittest.TestCase):
    def make_prop(self, line=1.5):
        return SimpleNamespace(
            line=line,
            prop_type="hits",
            game_time=datetime(2026, 8, 4),
            player=SimpleNamespace(sport="MLB"),
        )

    def make_log(self, day, value):
        return SimpleNamespace(
            game_date=datetime(2026, 7, day),
            opponent="Opponent",
            stats={"hits": value},
            source="mlb_stats_api",
        )

    def test_uses_exact_line_and_orders_most_recent_first(self):
        logs = [self.make_log(day, value) for day, value in [(1, 1), (2, 2), (3, 3)]]
        trends = build_exact_line_trends(self.make_prop(), logs)

        self.assertEqual(trends["l5"]["hits"], 2)
        self.assertEqual(trends["l5"]["decisions"], 3)
        self.assertEqual(trends["recent_games"][0]["value"], 3.0)

    def test_excludes_pushes_from_hit_rate_denominator(self):
        logs = [self.make_log(day, value) for day, value in [(1, 2), (2, 2.5), (3, 1)]]
        trends = build_exact_line_trends(self.make_prop(line=2), logs)

        self.assertEqual(trends["l5"]["pushes"], 1)
        self.assertEqual(trends["l5"]["decisions"], 2)
        self.assertEqual(trends["l5"]["hit_rate"], 0.5)

    def test_returns_none_when_stat_history_is_missing(self):
        log = SimpleNamespace(
            game_date=datetime(2026, 7, 1),
            opponent="Opponent",
            stats={"runs": 1},
        )
        self.assertIsNone(build_exact_line_trends(self.make_prop(), [log]))

    def test_cross_year_seasons_cover_basketball_hockey_and_football(self):
        for sport, season, dates in [("NBA", 2026, [datetime(2025, 11, 1), datetime(2026, 3, 1)]),
                                     ("NHL", 2026, [datetime(2025, 11, 1), datetime(2026, 3, 1)]),
                                     ("NFL", 2025, [datetime(2025, 11, 1), datetime(2026, 1, 1)])]:
            logs = [SimpleNamespace(game_date=date, source=f"espn_{sport.lower()}",
                                    stats={"points": 10}, opponent="Opponent") for date in dates]
            self.assertEqual(len(build_line_results(sport, "points", 5, season, logs)), 2)
            self.assertEqual(build_line_results(sport, "points", 5, season + 1, logs), [])

    def test_rejects_mock_future_and_invalid_statistics(self):
        today = datetime.utcnow()
        logs = [SimpleNamespace(game_date=today, source=source, stats={"hits": value}, opponent="X")
                for source, value in [("mock", 3), (None, 3), ("mlb_stats_api", "NaN"),
                                      ("mlb_stats_api", True), ("mlb_stats_api", "--")]]
        logs.append(SimpleNamespace(game_date=today + timedelta(days=2), source="mlb_stats_api",
                                    stats={"hits": 2}, opponent="X"))
        self.assertEqual(build_line_results("MLB", "hits", 1.5, today.year, logs), [])

    def test_duplicate_provider_games_count_once(self):
        log = self.make_log(1, 3)
        log.external_game_id = "provider-game-1"
        trends = build_exact_line_trends(self.make_prop(), [log, log])
        self.assertEqual(trends["l5"]["games"], 1)

    def test_mlb_today_date_only_stats_not_counted_before_completion_known(self):
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        log = SimpleNamespace(game_date=today, source="mlb_stats_api", stats={"hits": 3}, opponent="X")
        self.assertEqual(build_line_results("MLB", "hits", 1.5, today.year, [log]), [])


if __name__ == "__main__":
    unittest.main()
