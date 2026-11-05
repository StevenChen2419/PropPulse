import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as Namespace

def SimpleNamespace(**kwargs):
    if "sportsbook" in kwargs and "side" not in kwargs and "id" not in kwargs:
        kwargs.setdefault("provider_observed_at", datetime.now(timezone.utc))
    return Namespace(**kwargs)
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.models import Prop, Slip, SlipItem, User
from app.routers.interactions import router
from app.services.slip_service import slip_selection
from app.routers.users import get_slip


class SlipSideTests(unittest.TestCase):
    def setUp(self):
        self.prop = SimpleNamespace(
            id="prop-1", sportsbook="FanDuel", line=1.5,
            over_odds=-110, under_odds=-105, book_offers=[], popularity_count=0,
            is_active=True, odds_event_id="provider-event",
            game_time=datetime.now(timezone.utc) + timedelta(days=1),
        )
        self.prop.book_offers = [SimpleNamespace(sportsbook="FanDuel", line=1.5,
            over_odds=-110, under_odds=-105, provider_observed_at=datetime.now(timezone.utc))]
        self.slip = SimpleNamespace(id="slip-1")
        self.item = None
        self.db = MagicMock()
        self.db.query.side_effect = self.query
        app = FastAPI()
        app.include_router(router, prefix="/interactions")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1")
        self.client = TestClient(app)

    def query(self, model):
        result = {Prop: self.prop, Slip: self.slip, SlipItem: self.item, User: SimpleNamespace(id="user-1")}[model]
        query = MagicMock()
        query.filter.return_value.first.return_value = result
        return query

    def post(self, **fields):
        return self.client.post(
            "/interactions/prop-1", json={"action": "add_to_slip", **fields}
        )

    def assertSelection(self, actual, expected):
        self.assertEqual({key: actual[key] for key in expected}, expected)

    def added_items(self):
        return [call.args[0] for call in self.db.add.call_args_list
                if isinstance(call.args[0], SlipItem)]

    def test_creates_under_item(self):
        self.assertEqual(self.post(side="under").status_code, 200)
        self.assertEqual([item.side for item in self.added_items()], ["under"])
        self.db.commit.assert_called_once()

    def test_creates_open_slip_when_missing(self):
        self.slip = None
        self.assertEqual(self.post(side="under").status_code, 200)
        self.db.flush.assert_called_once()
        self.assertTrue(any(isinstance(call.args[0], Slip) for call in self.db.add.call_args_list))
        self.assertEqual(self.added_items()[0].side, "under")

    def test_switches_existing_side_without_duplicate(self):
        self.item = SimpleNamespace(side="over")
        self.assertEqual(self.post(side="under").status_code, 200)
        self.assertEqual(self.item.side, "under")
        self.assertEqual(self.added_items(), [])

    def test_omitted_side_defaults_to_over(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.added_items()[0].side, "over")

    def test_invalid_side_is_rejected_before_database_access(self):
        self.assertEqual(self.post(side="invalid").status_code, 422)
        self.db.query.assert_not_called()

    def test_null_primary_book_side_rejects_legacy_and_other_book_prices(self):
        self.prop.book_offers = [
            SimpleNamespace(sportsbook="FanDuel", line=1.5, over_odds=-110, under_odds=None),
            SimpleNamespace(sportsbook="DraftKings", line=1.5, over_odds=-110, under_odds=100),
        ]
        self.assertEqual(self.post(side="under").status_code, 400)
        self.db.add.assert_not_called()
        self.db.commit.assert_not_called()
        self.assertEqual(self.prop.popularity_count, 0)

    def test_different_line_or_sportsbook_cannot_supply_selected_side(self):
        for book, line in [("FanDuel", 2.5), ("DraftKings", 1.5)]:
            with self.subTest(book=book, line=line):
                self.prop.book_offers = [SimpleNamespace(
                    sportsbook=book, line=line, over_odds=-110, under_odds=100
                )]
                self.assertEqual(self.post(side="under").status_code, 400)
        self.db.commit.assert_not_called()

    def test_exact_book_available_side_is_accepted(self):
        self.prop.under_odds = None
        self.prop.book_offers = [SimpleNamespace(
            sportsbook="FanDuel", line=1.5, over_odds=None, under_odds=100
        )]
        self.assertEqual(self.post(side="under").status_code, 200)
        self.assertEqual(self.added_items()[0].side, "under")

    def test_legacy_null_side_is_unavailable(self):
        self.prop.book_offers[0].over_odds = None
        self.assertEqual(self.post().status_code, 400)
        self.db.commit.assert_not_called()

    def test_selects_other_sportsbook_and_different_line(self):
        self.prop.book_offers = [SimpleNamespace(
            sportsbook="DraftKings", line=2.5, over_odds=120, under_odds=-140
        )]
        self.assertEqual(self.post(side="under", sportsbook="DraftKings", line=2.5001).status_code, 400)
        self.db.commit.assert_not_called()
        response = self.post(side="under", sportsbook="DraftKings", line=2.5)
        self.assertEqual(response.status_code, 200)
        self.assertSelection(response.json()["selection"], {"sportsbook": "DraftKings", "line": 2.5, "odds": -140})
        item = self.added_items()[0]
        self.assertEqual((item.sportsbook, item.line), ("DraftKings", 2.5))
        self.assertSelection(slip_selection(item, self.prop), {"sportsbook": "DraftKings", "line": 2.5, "odds": -140})
        self.prop.book_offers[0].line = 3.5
        self.assertSelection(slip_selection(item, self.prop), {"sportsbook": "DraftKings", "line": 2.5, "odds": None})

    def test_switch_updates_book_and_line(self):
        self.item = SimpleNamespace(side="over", sportsbook="Old", line=9.5)
        response = self.post(side="under")
        self.assertEqual(response.status_code, 200)
        self.assertSelection(response.json()["selection"], {"sportsbook": "FanDuel", "line": 1.5, "odds": -105})
        self.assertEqual((self.item.side, self.item.sportsbook, self.item.line), ("under", "FanDuel", 1.5))

    def test_rejects_unlisted_or_incomplete_selection(self):
        self.assertEqual(self.post(sportsbook="DraftKings", line=1.5).status_code, 400)
        self.assertEqual(self.post(sportsbook="FanDuel").status_code, 422)
        self.assertEqual(self.post(line=1.5).status_code, 422)
        self.assertEqual(self.post(sportsbook="FanDuel", line="NaN").status_code, 422)
        self.db.commit.assert_not_called()

    def test_invalid_prices_are_unavailable(self):
        for odds in [0, 99, -99, float("nan"), float("inf")]:
            with self.subTest(odds=odds):
                self.prop.book_offers[0].over_odds = odds
                self.assertEqual(self.post().status_code, 400)

    def test_legacy_item_requires_reselection_and_missing_prop_is_unavailable(self):
        item = SimpleNamespace(side="under", sportsbook=None, line=None)
        self.assertSelection(slip_selection(item, self.prop), {"sportsbook": None, "line": None, "odds": None})
        self.assertSelection(slip_selection(item, None), {"sportsbook": None, "line": None, "odds": None})

    def test_removed_saved_offer_does_not_use_another_book(self):
        item = SimpleNamespace(side="under", sportsbook="DraftKings", line=1.5)
        self.assertIsNone(slip_selection(item, self.prop)["odds"])

    def test_saved_selection_survives_database_reload_and_get_response(self):
        engine = create_engine("sqlite://")
        Slip.__table__.create(engine)
        SlipItem.__table__.create(engine)
        with Session(engine) as db:
            slip = Slip(user_id="abcdefab-abcd-abcd-abcd-abcdefabcdef")
            db.add(slip)
            db.flush()
            item = SlipItem(slip_id=slip.id,
                            prop_id="bcdefabc-bcde-bcde-bcde-bcdefabcdefa",
                            sportsbook="DraftKings", line=2.5, side="under")
            db.add(item)
            db.commit()
            db.expunge_all()
            reloaded = db.query(SlipItem).one()
            self.assertEqual((reloaded.sportsbook, reloaded.line, reloaded.side), ("DraftKings", 2.5, "under"))
            self.prop.book_offers = [SimpleNamespace(sportsbook="DraftKings", line=2.5, under_odds=125)]
            self.prop.player_id = "player-1"
            self.prop.id = reloaded.prop_id
            query_db = MagicMock()
            slip_query, items_query, prop_query, fatigue_query = [MagicMock() for _ in range(4)]
            slip_query.filter.return_value.first.return_value = db.query(Slip).one()
            items_query.filter.return_value.all.return_value = [reloaded]
            prop_query.join.return_value.options.return_value.filter.return_value.all.return_value = [self.prop]
            fatigue_query.filter.return_value.all.return_value = []
            query_db.query.side_effect = [slip_query, items_query, prop_query, fatigue_query]
            with patch("app.routers.users._prop_out", return_value={"sportsbook": "FanDuel", "line": 1.5}), \
                    patch('app.routers.users.load_game_logs', return_value={}):
                response = get_slip(SimpleNamespace(id="abcdefab-abcd-abcd-abcd-abcdefabcdef"), query_db)
            result = response["slip"]["items"][0]
            self.assertSelection(result["selection"], {"sportsbook": "DraftKings", "line": 2.5, "odds": 125})
            self.assertEqual(result["prop"]["sportsbook"], "FanDuel")
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
