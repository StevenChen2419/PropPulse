import unittest
from types import SimpleNamespace

from app.services.discovery_service import score_discovery_prop


def trend_window(hits, decisions):
    return {
        "games": decisions,
        "decisions": decisions,
        "hits": hits,
        "pushes": 0,
        "hit_rate": hits / decisions if decisions else None,
    }


class DiscoveryScoringTests(unittest.TestCase):
    def make_prop(self, line=1.5, old_line=1.5):
        return SimpleNamespace(line=line, line_24h_ago=old_line)

    def make_trends(self, l5_hits, l10_hits, season_hits, season_games=20):
        return {
            "l5": trend_window(l5_hits, 5),
            "l10": trend_window(l10_hits, 10),
            "season_window": trend_window(season_hits, season_games),
        }

    def test_stronger_exact_line_form_scores_higher(self):
        strong = score_discovery_prop(
            self.make_prop(),
            self.make_trends(5, 8, 15),
            {"sportsbook": "FanDuel", "odds": 105, "line": 1.5},
            5,
        )
        weak = score_discovery_prop(
            self.make_prop(),
            self.make_trends(1, 3, 8),
            {"sportsbook": "FanDuel", "odds": -130, "line": 1.5},
            2,
        )
        self.assertGreater(strong["score"], weak["score"])

    def test_reasons_expose_line_record_and_best_price(self):
        result = score_discovery_prop(
            self.make_prop(line=0.5),
            self.make_trends(4, 7, 14),
            {"sportsbook": "DraftKings", "odds": 110, "line": 0.5},
            4,
        )
        self.assertIn("7/10 over 0.5", result["reasons"][0])
        self.assertIn("+110 at DraftKings", result["reasons"][1])

    def test_missing_history_is_not_discoverable(self):
        self.assertIsNone(score_discovery_prop(self.make_prop(), None, None, 0))

    def test_tiny_samples_are_not_discoverable(self):
        trends = {
            "l5": trend_window(2, 2),
            "l10": trend_window(2, 2),
            "season_window": trend_window(2, 2),
        }
        self.assertIsNone(score_discovery_prop(self.make_prop(), trends, None, 1))


if __name__ == "__main__":
    unittest.main()
