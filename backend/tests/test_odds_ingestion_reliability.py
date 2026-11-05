import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from scripts.fetch_odds import (
    CACHE_TTL,
    cache_offer_is_fresh,
    determine_availability,
    extract_provider_error,
    should_replace_all_offers,
)


class OddsIngestionReliabilityTests(unittest.TestCase):
    def test_successful_http_response_never_proves_whole_sport_replacement(self):
        status = {"market_requests_failed": 0, "live_props_matched": 12}
        self.assertFalse(should_replace_all_offers([{"line": 1.5}], status))
        self.assertEqual(determine_availability(status), "live")

    def test_empty_success_preserves_existing_offers(self):
        status = {
            "market_requests_failed": 0,
            "live_props_matched": 0,
            "cached_live_props": 0,
            "events_found": 4,
            "provider_http_status": 200,
        }
        self.assertFalse(should_replace_all_offers([], status))
        self.assertEqual(determine_availability(status), "unavailable")

    def test_partial_response_preserves_untouched_offers(self):
        status = {"market_requests_failed": 1, "live_props_matched": 3}
        self.assertFalse(should_replace_all_offers([{"line": 1.5}], status))

    def test_failed_response_uses_last_known_availability(self):
        status = {
            "market_requests_failed": 1,
            "live_props_matched": 0,
            "cached_live_props": 8,
            "events_found": 2,
            "provider_http_status": 401,
        }
        self.assertFalse(should_replace_all_offers([], status))
        self.assertEqual(determine_availability(status), "last_known")

    def test_successful_empty_schedule_reports_no_games(self):
        status = {
            "live_props_matched": 0,
            "cached_live_props": 0,
            "events_found": 0,
            "provider_http_status": 200,
        }
        self.assertEqual(determine_availability(status), "no_games")

    def test_cache_expires_at_ttl_or_game_start(self):
        now = datetime(2026, 8, 14, 18, 0)
        offer = SimpleNamespace(provider_observed_at=now - CACHE_TTL + timedelta(minutes=1))
        upcoming = SimpleNamespace(game_time=now + timedelta(minutes=1))
        started = SimpleNamespace(game_time=now)
        expired_offer = SimpleNamespace(provider_observed_at=now - CACHE_TTL - timedelta(microseconds=1))

        self.assertTrue(cache_offer_is_fresh(upcoming, offer, now))
        self.assertFalse(cache_offer_is_fresh(started, offer, now))
        self.assertFalse(cache_offer_is_fresh(upcoming, expired_offer, now))

    def test_provider_error_details_are_preserved(self):
        self.assertEqual(
            extract_provider_error({"error_code": "OUT_OF_USAGE_CREDITS", "message": "Quota exhausted"}),
            ("OUT_OF_USAGE_CREDITS", "Quota exhausted"),
        )


if __name__ == "__main__":
    unittest.main()
