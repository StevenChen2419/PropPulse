"""Inventory safety regressions using isolated stores and real PostgreSQL opt-in.

These assertions complement the captured performance oracle: availability must
never conceal identity conflicts, and ordinary pagination must retain encounter
order through equal-score ties. They perform no application startup or provider HTTP.
"""
from datetime import timedelta
import os
import unittest

import test_event_apis as existing
from app.services.game_identity_service import prop_context


class InventoryEquivalenceScenarios:
    fixture = existing.EventApiScenarios.fixture
    new_event = existing.EventApiScenarios.new_event
    new_prop = existing.EventApiScenarios.new_prop
    get = existing.EventApiScenarios.get
    games = existing.EventApiScenarios.games

    def legacy_pair(self, **changes):
        first = self.new_prop(self.players[0], game_time=self.now + timedelta(days=4))
        second = self.new_prop(self.players[0], game_time=first.game_time,
                               opponent="Conflicting Opponent", **changes)
        return first, second

    def assert_legacy_conflict(self, first):
        key = prop_context(first)["game_key"]
        for route in ("game", "feed", "discover"):
            with self.subTest(route=route):
                self.assertEqual(self.get(route, game_key=key).status_code, 409)
        self.assertNotIn(key, {game["game_key"] for game in self.games()})

    def test_inactive_legacy_conflict_survives_inventory_filtering(self):
        first, _ = self.legacy_pair(is_active=False)
        self.assert_legacy_conflict(first)
        self.assertIn(first.id, {prop["id"] for prop in self.get("feed").json()["props"]})

    def test_expired_legacy_conflict_survives_inventory_filtering(self):
        first, second = self.legacy_pair()
        second.book_offers[0].provider_observed_at -= timedelta(hours=7)
        self.assert_legacy_conflict(first)

    def test_unresolved_inactive_namespace_conflict_is_not_ignored(self):
        first = self.new_prop(self.players[0], game_time=self.now + timedelta(days=4))
        self.new_prop(self.players[0], opponent=None, is_active=False)
        self.assert_legacy_conflict(first)

    def test_collision_outside_games_limit_does_not_surface_later(self):
        first, second = self.legacy_pair(is_active=False)
        second.game_time = self.now + timedelta(days=20)
        self.assertEqual(len(self.get("games", limit=1).json()["games"]), 1)
        self.assert_legacy_conflict(first)

    def test_empty_event_collision_survives_schedule_correction(self):
        first = self.new_prop(self.players[0], game_time=self.now + timedelta(days=4))
        event = self.new_event("corrected-empty", scheduled_start_at=self.now + timedelta(days=8))
        self.assertIn(first.id, {prop["id"] for prop in self.get("feed").json()["props"]})
        self.assertIn(prop_context(first)["game_key"], {game["game_key"] for game in self.games()})
        event.scheduled_start_at = first.game_time
        self.assert_legacy_conflict(first)
        body = self.get("game", event_id=event.id).json()
        self.assertEqual(body["props"], [])
        self.assertEqual(body["event_id"], event.id)

    def test_equal_rank_feed_pages_reconstruct_complete_feed_order(self):
        # All ten fixture props have identical ranking inputs. Stable ties must
        # remain intact across page boundaries and beyond the inventory end.
        complete = self.get("feed", limit=50).json()
        ids = [prop["id"] for prop in complete["props"]]
        self.assertEqual(len(ids), 10)
        paged = []
        for offset in range(0, 12, 3):
            body = self.get("feed", limit=3, offset=offset).json()
            self.assertEqual(body["total"], 10)
            paged.extend(prop["id"] for prop in body["props"])
        self.assertEqual(paged, ids)
        deep = self.get("feed", limit=3, offset=10000).json()
        self.assertEqual(deep["props"], [])
        self.assertEqual(deep["total"], 10)


class InventoryEquivalenceSQLiteTests(InventoryEquivalenceScenarios, unittest.TestCase):
    setUp = existing.EventApiSQLiteTests.setUp


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit isolated PostgreSQL URL unset")
class InventoryEquivalencePostgresTests(InventoryEquivalenceScenarios, unittest.TestCase):
    setUpClass = classmethod(existing.EventApiPostgresTests.setUpClass.__func__)
    remove_schema = existing.EventApiPostgresTests.remove_schema
    setUp = existing.EventApiPostgresTests.setUp
