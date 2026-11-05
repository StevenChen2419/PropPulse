import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from app.routers.props import eastern_day_priority, odds_freshness, best_line_fields


class EasternDayPriorityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 8, 1, 0, tzinfo=timezone.utc)

    def test_late_evening_eastern_game_is_today(self):
        game_time = datetime(2026, 8, 8, 2, 30)
        self.assertEqual(eastern_day_priority(game_time, self.now), 0)

    def test_next_eastern_day_is_future(self):
        game_time = datetime(2026, 8, 8, 17, 0)
        self.assertEqual(eastern_day_priority(game_time, self.now), 1)

    def test_missing_game_time_sorts_last(self):
        self.assertEqual(eastern_day_priority(None, self.now), 2)


class FreshnessTests(unittest.TestCase):
    def prop(self, offers):
        return SimpleNamespace(book_offers=offers, line=2.5, sportsbook="FanDuel",
                               is_active=True, odds_event_id="event",
                               game_time=datetime.now(timezone.utc) + timedelta(days=1))

    def offer(self, age):
        return SimpleNamespace(provider_observed_at=datetime.utcnow() - timedelta(minutes=age),
                               sportsbook="FanDuel", line=2.5, over_odds=-110, under_odds=-110)

    def test_live_and_last_known_use_real_observation_time(self):
        for age, source in [(5, "live"), (60, "last_known"), (361, "unavailable")]:
            offer = self.offer(age)
            result = odds_freshness(self.prop([offer]))
            self.assertEqual(result["source"], source)
            self.assertEqual(result["refreshed_at"], offer.provider_observed_at.replace(tzinfo=timezone.utc).isoformat())

    def test_expired_books_do_not_win_best_price(self):
        fresh, expired = self.offer(5), self.offer(361)
        expired.over_odds = 200
        expired.sportsbook = "DraftKings"
        prop = self.prop([fresh, expired])
        result = best_line_fields(prop)
        self.assertEqual(result["sportsbook_count"], 1)
        self.assertEqual(result["best_over"]["odds"], -110)


if __name__ == "__main__":
    unittest.main()
