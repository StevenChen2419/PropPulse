import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.models import Prop
from app.routers.users import user_router
from app.services.parlay_service import estimate_parlay, historical_rho, joint_probability


class ParlayTests(unittest.TestCase):
    def setUp(self):
        self.props = [NS(id=f"00000000-0000-0000-0000-{i:012d}", player_id=str(i),
                         player=NS(sport="WNBA"), prop_type="points", is_active=True,
                         odds_event_id="event-1", game_time=datetime(2025, 6, 1),
                         sportsbook="FanDuel", line=10.5, over_odds=100, under_odds=100,
                         book_offers=[]) for i in (1, 2)]
        self.items = [NS(prop_id=p.id, sportsbook="FanDuel", line=10.5, side="over") for p in self.props]
        for prop in self.props:
            prop.book_offers = [NS(sportsbook="FanDuel", line=10.5, over_odds=100,
                                   under_odds=100, provider_observed_at=datetime(2025, 5, 31, 23))]
        self.clock = __import__("unittest.mock", fromlist=["patch"]).patch("app.services.parlay_service.datetime")
        clock = self.clock.start()
        clock.side_effect = datetime
        clock.now.return_value = datetime(2025, 6, 1, 0, 0) - timedelta(minutes=30)
        self.addCleanup(self.clock.stop)
        self.logs = []
        self.db = MagicMock()
        def query(model):
            result = MagicMock()
            result.filter.return_value.all.return_value = self.props if model is Prop else self.logs
            return result
        self.db.query.side_effect = query

    def test_independent_exact_product(self):
        self.props[1].odds_event_id = "event-2"
        result = estimate_parlay(self.db, self.items)
        self.assertEqual((result["decimal"], result["american"], result["method"]), (4, 300, "independent"))

    def test_correlation_direction_and_zero_baseline(self):
        positive = estimate_parlay(self.db, self.items, .5)
        zero = estimate_parlay(self.db, self.items, 0)
        self.items[1].side = "under"
        negative = estimate_parlay(self.db, self.items, .5)
        self.assertLess(positive["decimal"], zero["decimal"])
        self.assertGreater(negative["decimal"], zero["decimal"])
        self.assertAlmostEqual(positive["decimal"], 3, delta=.03)
        self.assertAlmostEqual(negative["decimal"], 6, delta=.05)
        self.assertEqual(positive["assumed_pairs"], 1)
        self.assertTrue(any("uncalibrated" in w for w in positive["warnings"]))

    def test_invalid_and_duplicate_selections(self):
        for attribute, value in [("is_active", False), ("odds_event_id", "mock-1"),
                                 ("game_time", None)]:
            old = getattr(self.props[0], attribute)
            setattr(self.props[0], attribute, value)
            with self.subTest(attribute=attribute):
                self.assertIsNone(estimate_parlay(self.db, self.items)["decimal"])
            setattr(self.props[0], attribute, old)
        self.assertIsNone(estimate_parlay(self.db, [self.items[0], self.items[0]])["decimal"])
        self.items[1].sportsbook = "Other"
        self.assertIn("one sportsbook", estimate_parlay(self.db, self.items)["reason"])

    def test_missing_offer_does_not_borrow_price(self):
        self.items[0].line = 11.5
        self.assertIsNone(estimate_parlay(self.db, self.items)["decimal"])

    def test_composite_overlap_cannot_price_impossible_combination(self):
        self.props[1].player_id = self.props[0].player_id
        self.props[1].prop_type = "pra"
        self.props[0].line = self.items[0].line = 30.5
        self.props[1].line = self.items[1].line = 20.5
        self.items[1].side = "under"
        for prop in self.props:
            prop.book_offers[0].line = prop.line
        for items in (self.items, list(reversed(self.items))):
            result = estimate_parlay(self.db, items)
            self.assertIsNone(result["decimal"])
            self.assertIn("overlaps", result["reason"])

    def history(self, count=30):
        return {p.player_id: [NS(sport="WNBA", source="espn_wnba", external_game_id=str(i),
                                 game_date=datetime(2025, 1, 1) + timedelta(days=i),
                                 stats={"points": i}) for i in range(count)] for p in self.props}

    def test_historical_rank_correlation_shrinkage(self):
        rho, count = historical_rho(*self.props, self.history())
        self.assertEqual(count, 30)
        self.assertAlmostEqual(rho, .5)

    def test_history_excludes_untrusted_future_old_and_unmatched_games(self):
        logs = self.history()
        for entries in logs.values():
            entries[0].source = "synthetic"
            entries[1].game_date = datetime(2025, 6, 1)
            entries[2].game_date = datetime(2023, 12, 31)
            entries[3].external_game_id = None
            entries[4].sport = "NBA"
        logs["1"][5].external_game_id = "unmatched"
        rho, count = historical_rho(*self.props, logs)
        self.assertEqual(count, 24)
        self.assertAlmostEqual(rho, 24 / 54)

    def test_insufficient_constant_and_invalid_pra_history(self):
        self.assertIsNone(historical_rho(*self.props, self.history(19))[0])
        logs = self.history()
        for entries in logs.values():
            for log in entries:
                log.stats = {"points": 1}
        self.assertIsNone(historical_rho(*self.props, logs)[0])
        self.props[0].prop_type = "pra"
        logs["1"][0].stats = {"points": None, "rebounds": 2, "assists": 3}
        self.assertIsNone(historical_rho(*self.props, logs)[0])

    def test_joint_probability_repair_and_rare_event_guard(self):
        matrix = np.array([[1, .9, .9], [.9, 1, -.9], [.9, -.9, 1]])
        probability = joint_probability([.5] * 3, matrix)
        self.assertTrue(probability is None or 0 < probability <= .5)
        self.assertIsNone(joint_probability([.01, .01], np.array([[1, -.6], [-.6, 1]])))

    def test_endpoint_and_validation(self):
        app = FastAPI()
        app.include_router(user_router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: NS(id="user")
        client = TestClient(app)
        body = {"items": [vars(item) for item in self.items]}
        self.assertEqual(client.post("/me/slip/estimate", json=body).status_code, 200)
        for changes in [{"items": []}, {"assumed_correlation": -.1}, {"assumed_correlation": .7},
                        {"assumed_correlation": "NaN"},
                        {"items": [{**vars(self.items[0]), "prop_id": "invalid"}, vars(self.items[1])]}]:
            self.db.reset_mock()
            self.assertEqual(client.post("/me/slip/estimate", json={**body, **changes}).status_code, 422)
            self.db.query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
