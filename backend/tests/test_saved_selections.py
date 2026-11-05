"""Exact selection regressions using disposable SQLite and isolated FastAPI apps."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import ARRAY, JSON, MetaData, create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import get_db
from app.models import Event, FatigueScore, Interaction, Player, Prop, PropBook, SavedProp, Slip, SlipItem, User
from app.routers.interactions import router as interaction_router
from app.routers.users import user_router
from app.services.slip_service import slip_selection


class SavedSelectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        # Clone only test tables, adapting PostgreSQL preference arrays locally.
        metadata = MetaData()
        for model in (User, Event, Player, Prop, PropBook, SavedProp, Slip, SlipItem, Interaction, FatigueScore):
            table = model.__table__.to_metadata(metadata)
            for column in table.columns:
                if isinstance(column.type, ARRAY):
                    column.type = JSON()
        metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.user_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.other_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        with self.engine.begin() as connection:
            connection.execute(metadata.tables["users"].insert(), [
                dict(id=uid, email=f"{uid}@test.invalid", hashed_password="unused")
                for uid in (self.user_id, self.other_id)
            ])
        self.now = datetime.now(timezone.utc).replace(tzinfo=None)
        player = Player(name="Test Player", team="Test", team_abbr="TST", sport="NBA")
        self.db.add(player)
        self.db.flush()
        self.prop = Prop(player_id=player.id, prop_type="points", line=20.5,
            sportsbook="FanDuel", odds_event_id="stored-provider-event", game_time=self.now + timedelta(days=1))
        self.db.add(self.prop)
        self.db.flush()
        self.primary = PropBook(prop_id=self.prop.id, sportsbook="FanDuel", line=20.5,
            over_odds=-110, under_odds=-105, provider_observed_at=self.now - timedelta(minutes=2))
        self.alternative = PropBook(prop_id=self.prop.id, sportsbook="DraftKings", line=21.5,
            over_odds=120, under_odds=-140, provider_observed_at=self.now - timedelta(minutes=3))
        self.db.add_all([self.primary, self.alternative])
        self.db.commit()
        self.current_user = SimpleNamespace(id=self.user_id)
        app = FastAPI()
        app.include_router(user_router, prefix="/users")
        app.include_router(interaction_router, prefix="/interactions")
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.addCleanup(self.db.rollback)

    def selection(self, **changes):
        return {"sportsbook": "FanDuel", "line": 20.5, "side": "over", **changes}

    def save(self, **changes):
        return self.client.post(f"/users/me/saved/selections/{self.prop.id}", json=self.selection(**changes))

    def slip_item(self):
        slip = Slip(user_id=self.user_id)
        self.db.add(slip)
        self.db.flush()
        item = SlipItem(slip_id=slip.id, prop_id=self.prop.id, **self.selection(), original_odds=-115,
                        original_observed_at=self.now - timedelta(minutes=10))
        other = SlipItem(slip_id=slip.id, prop_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
                         sportsbook="FanDuel", line=7.5, side="under")
        self.db.add_all([item, other])
        self.db.commit()
        return item, other

    def edit_slip(self, **changes):
        return self.client.patch(f"/users/me/slip/items/{self.prop.id}", json=self.selection(**changes))

    def test_authentication_required(self):
        self.app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.save().status_code, 401)
        self.assertEqual(self.client.get("/users/me/saved").status_code, 401)
        self.assertEqual(self.edit_slip().status_code, 401)

    def test_create_captures_stored_price_and_provider_observation(self):
        response = self.save()
        self.assertEqual(response.status_code, 200, response.text)
        row = self.db.query(SavedProp).one()
        self.assertEqual(row.id, response.json()["id"])
        self.assertEqual((row.sportsbook, row.line, row.side, row.original_odds), ("FanDuel", 20.5, "over", -110))
        self.assertEqual(row.original_observed_at, self.primary.provider_observed_at)

    def test_duplicate_save_keeps_identity_and_original_evidence_after_offer_disappears(self):
        first = self.save().json()["id"]
        self.db.delete(self.primary)
        self.db.commit()
        self.assertEqual(self.save().json()["id"], first)
        self.assertEqual(self.db.query(SavedProp).count(), 1)
        self.assertEqual(self.db.query(SavedProp).one().original_odds, -110)

    def test_bookmark_coexists_and_unsave_does_not_remove_exact_selection(self):
        exact_id = self.save().json()["id"]
        response = self.client.post(f"/interactions/{self.prop.id}", json={"action": "save"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.query(SavedProp).count(), 2)
        self.client.delete(f"/interactions/{self.prop.id}/save")
        self.assertEqual(self.db.query(SavedProp).one().id, exact_id)

    def test_list_distinguishes_bookmarks_and_exact_selections_and_retains_expired(self):
        selection_id = self.save().json()["id"]
        self.db.add(SavedProp(user_id=self.user_id, prop_id=self.prop.id))
        self.primary.provider_observed_at = self.now - timedelta(hours=7)
        self.db.commit()
        with patch("app.routers.users.load_game_logs", return_value={}), \
             patch("app.routers.users._prop_out", return_value={"id": self.prop.id}):
            response = self.client.get("/users/me/saved")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["saved"]), 1)
        exact = response.json()["selections"][0]
        self.assertEqual(exact["id"], selection_id)
        self.assertEqual(exact["selection"]["availability"], "expired")
        self.assertEqual(exact["selection"]["original_odds"], -110)
        self.assertIsNone(exact["selection"]["odds"])

    def test_exact_delete_preserves_bookmark(self):
        selection_id = self.save().json()["id"]
        self.db.add(SavedProp(user_id=self.user_id, prop_id=self.prop.id))
        self.db.commit()
        response = self.client.delete(f"/users/me/saved/selections/{selection_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.db.query(SavedProp).one().side)

    def test_exact_routes_cannot_convert_or_remove_generic_bookmark(self):
        bookmark = SavedProp(user_id=self.user_id, prop_id=self.prop.id)
        self.db.add(bookmark)
        self.db.commit()
        path = f"/users/me/saved/selections/{bookmark.id}"
        self.assertEqual(self.client.patch(path, json=self.selection()).status_code, 404)
        self.assertEqual(self.client.delete(path).status_code, 404)
        self.assertIsNone(self.db.query(SavedProp).one().side)

    def test_other_user_cannot_edit_or_delete_saved_selection(self):
        selection_id = self.save().json()["id"]
        self.current_user = SimpleNamespace(id=self.other_id)
        path = f"/users/me/saved/selections/{selection_id}"
        self.assertEqual(self.client.patch(path, json=self.selection(side="under")).status_code, 404)
        self.assertEqual(self.client.delete(path).status_code, 404)
        self.assertEqual(self.db.query(SavedProp).one().side, "over")
        self.assertEqual(self.client.get("/users/me/saved").json(), {"saved": [], "selections": []})

    def test_saved_edit_preserves_row_id_and_rejects_duplicate(self):
        first = self.save().json()["id"]
        second = self.save(side="under").json()["id"]
        path = f"/users/me/saved/selections/{first}"
        self.assertEqual(self.client.patch(path, json=self.selection(side="under")).status_code, 409)
        response = self.client.patch(path, json=self.selection(sportsbook="DraftKings", line=21.5, side="under"))
        self.assertEqual(response.json()["id"], first)
        self.assertEqual(self.db.get(SavedProp, first).original_odds, -140)
        self.assertEqual(self.db.get(SavedProp, second).side, "under")

    def test_failed_saved_create_and_edit_leave_committed_rows_intact(self):
        with patch.object(self.db, "commit", side_effect=RuntimeError("isolated write failure")):
            self.assertEqual(self.save().status_code, 500)
        self.assertEqual(self.db.query(SavedProp).count(), 0)
        selection_id = self.save().json()["id"]
        with patch.object(self.db, "commit", side_effect=RuntimeError("isolated write failure")):
            response = self.client.patch(f"/users/me/saved/selections/{selection_id}",
                json=self.selection(sportsbook="DraftKings", line=21.5, side="under"))
        self.assertEqual(response.status_code, 500)
        row = self.db.get(SavedProp, selection_id)
        self.assertEqual((row.sportsbook, row.line, row.side, row.original_odds), ("FanDuel", 20.5, "over", -110))

    def test_save_rejects_unknown_or_untrustworthy_offers_without_rows(self):
        for changes in ({"line": 20.5001}, {"sportsbook": "Unknown"}, {"line": 21.5}):
            self.assertEqual(self.save(**changes).status_code, 409)
        self.primary.provider_observed_at = None
        self.primary.ingested_at = self.now
        self.db.commit()
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.db.query(SavedProp).count(), 0)

    def test_last_known_can_be_saved_but_cannot_edit_slip(self):
        self.primary.provider_observed_at = self.now - timedelta(hours=1)
        self.db.commit()
        self.assertEqual(self.save().status_code, 200)
        item, _ = self.slip_item()
        self.assertEqual(self.edit_slip(side="under").status_code, 409)
        self.assertEqual(item.side, "over")

    def test_edit_slip_preserves_local_identity_and_other_items(self):
        item, other = self.slip_item()
        ids = item.id, other.id
        response = self.edit_slip(sportsbook="DraftKings", line=21.5, side="under")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], ids[0])
        self.db.expire_all()
        self.assertEqual(self.db.query(SlipItem).count(), 2)
        self.assertEqual((item.sportsbook, item.line, item.side, item.original_odds), ("DraftKings", 21.5, "under", -140))
        self.assertEqual((other.id, other.line, other.side), (ids[1], 7.5, "under"))

    def test_other_user_cannot_edit_slip(self):
        item, _ = self.slip_item()
        self.current_user = SimpleNamespace(id=self.other_id)
        self.assertEqual(self.edit_slip(side="under").status_code, 404)
        self.assertEqual(item.side, "over")

    def test_invalid_or_expired_slip_edit_preserves_original_selection(self):
        item, _ = self.slip_item()
        original = item.id, item.sportsbook, item.line, item.side, item.original_odds
        self.assertEqual(self.edit_slip(line=99.5).status_code, 409)
        self.alternative.provider_observed_at = self.now - timedelta(hours=7)
        self.db.commit()
        self.assertEqual(self.edit_slip(sportsbook="DraftKings", line=21.5).status_code, 409)
        self.assertEqual((item.id, item.sportsbook, item.line, item.side, item.original_odds), original)

    def test_failed_slip_commit_rolls_back_all_selection_fields(self):
        item, other = self.slip_item()
        original = item.id, item.sportsbook, item.line, item.side, item.original_odds, item.original_observed_at
        with patch.object(self.db, "commit", side_effect=RuntimeError("isolated write failure")):
            response = self.edit_slip(sportsbook="DraftKings", line=21.5, side="under")
        self.assertEqual(response.status_code, 500)
        self.assertEqual((item.id, item.sportsbook, item.line, item.side, item.original_odds, item.original_observed_at), original)
        self.assertEqual(other.side, "under")

    def test_identical_slip_edit_keeps_original_evidence(self):
        item, _ = self.slip_item()
        self.assertEqual(self.edit_slip().status_code, 200)
        self.assertEqual(item.original_odds, -115)

    def test_repeated_add_updates_existing_item_without_duplicates_or_price_recapture(self):
        item, _ = self.slip_item()
        item_id = item.id
        for _ in range(2):
            response = self.client.post(f"/interactions/{self.prop.id}",
                json={"action": "add_to_slip", **self.selection()})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.query(SlipItem).count(), 2)
        self.assertEqual((item.id, item.original_odds), (item_id, -115))

    def test_saved_and_edited_slip_survive_new_database_session(self):
        selection_id = self.save().json()["id"]
        item, _ = self.slip_item()
        item_id = item.id
        response = self.edit_slip(sportsbook="DraftKings", line=21.5, side="under")
        self.assertEqual(response.status_code, 200)
        with Session(self.engine) as reloaded:
            saved = reloaded.get(SavedProp, selection_id)
            slip = reloaded.get(SlipItem, item_id)
            self.assertEqual((saved.sportsbook, saved.line, saved.side, saved.original_odds),
                             ("FanDuel", 20.5, "over", -110))
            self.assertEqual((slip.sportsbook, slip.line, slip.side, slip.original_odds),
                             ("DraftKings", 21.5, "under", -140))
            self.assertEqual(slip.original_observed_at, self.alternative.provider_observed_at)

    def copy_saved_to_slip(self, selection_id):
        return self.client.post(f"/users/me/saved/selections/{selection_id}/slip")

    def test_copy_saved_selection_requires_authentication_and_ownership(self):
        selection_id = self.save().json()["id"]
        self.current_user = SimpleNamespace(id=self.other_id)
        self.assertEqual(self.copy_saved_to_slip(selection_id).status_code, 404)
        self.assertEqual(self.db.query(Slip).count(), 0)
        self.assertEqual(self.copy_saved_to_slip("dddddddd-dddd-dddd-dddd-dddddddddddd").status_code, 404)
        self.app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.copy_saved_to_slip(selection_id).status_code, 401)

    def test_generic_bookmark_cannot_be_copied_as_an_exact_selection(self):
        bookmark = SavedProp(user_id=self.user_id, prop_id=self.prop.id)
        self.db.add(bookmark)
        self.db.commit()
        self.assertEqual(self.copy_saved_to_slip(bookmark.id).status_code, 404)
        self.assertEqual(self.db.query(SlipItem).count(), 0)

    def test_copy_expired_saved_selection_keeps_evidence_and_is_excluded_from_estimates(self):
        selection_id = self.save().json()["id"]
        original_observed = self.primary.provider_observed_at
        self.primary.provider_observed_at = self.now - timedelta(hours=7)
        self.primary.ingested_at = self.now
        self.db.commit()
        response = self.copy_saved_to_slip(selection_id)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["selection"]
        self.assertEqual((result["availability"], result["actionable"], result["odds"]), ("expired", False, None))
        self.assertEqual(result["original_odds"], -110)
        item = self.db.query(SlipItem).one()
        item_id = item.id
        self.assertEqual((item.sportsbook, item.line, item.side), ("FanDuel", 20.5, "over"))
        self.assertEqual(item.original_observed_at, original_observed)
        second = Prop(player_id=self.prop.player_id, prop_type="assists", line=5.5,
            sportsbook="FanDuel", odds_event_id="stored-provider-event", game_time=self.now + timedelta(days=1))
        self.db.add(second)
        self.db.commit()
        estimate = self.client.post("/users/me/slip/estimate", json={"items": [
            {"prop_id": item.prop_id, "sportsbook": item.sportsbook, "line": item.line, "side": item.side},
            {"prop_id": second.id, "sportsbook": "FanDuel", "line": 5.5, "side": "over"},
        ]})
        self.assertEqual(estimate.status_code, 200, estimate.text)
        self.assertEqual(estimate.json()["availability"], "expired")
        self.assertIsNone(estimate.json()["decimal"])
        with Session(self.engine) as reloaded:
            persisted = reloaded.get(SlipItem, item_id)
            self.assertEqual((persisted.sportsbook, persisted.line, persisted.side, persisted.original_odds),
                             ("FanDuel", 20.5, "over", -110))
            self.assertEqual(persisted.original_observed_at, original_observed)

    def test_copy_saved_selection_is_idempotent_without_recapturing_price(self):
        selection_id = self.save().json()["id"]
        self.assertEqual(self.copy_saved_to_slip(selection_id).status_code, 200)
        item_id = self.db.query(SlipItem).one().id
        self.primary.over_odds = 125
        self.db.commit()
        response = self.copy_saved_to_slip(selection_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.db.query(Slip).count(), 1)
        item = self.db.query(SlipItem).one()
        self.assertEqual((item.id, item.original_odds), (item_id, -110))
        self.assertEqual(response.json()["selection"]["odds"], 125)

    def test_copy_saved_selection_conflict_preserves_original_and_other_items(self):
        selection_id = self.save(sportsbook="DraftKings", line=21.5, side="under").json()["id"]
        item, other = self.slip_item()
        original = item.id, item.sportsbook, item.line, item.side, item.original_odds
        response = self.copy_saved_to_slip(selection_id)
        self.assertEqual(response.status_code, 409, response.text)
        self.db.expire_all()
        self.assertEqual((item.id, item.sportsbook, item.line, item.side, item.original_odds), original)
        self.assertEqual((other.line, other.side), (7.5, "under"))
        self.assertEqual(self.db.query(SlipItem).count(), 2)

    def test_copy_missing_offer_and_missing_historical_price_stays_nullable(self):
        saved = SavedProp(user_id=self.user_id, prop_id=self.prop.id, **self.selection(),
                          original_odds=None, original_observed_at=None)
        self.db.add(saved)
        self.db.delete(self.primary)
        self.db.commit()
        response = self.copy_saved_to_slip(saved.id)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["selection"]
        self.assertIsNone(result["original_odds"])
        self.assertIsNone(result["original_observed_at"])
        self.assertIsNone(result["odds"])
        self.assertFalse(result["actionable"])

    def test_copy_saved_selection_commit_failure_rolls_back_new_slip(self):
        selection_id = self.save().json()["id"]
        with patch.object(self.db, "commit", side_effect=RuntimeError("isolated write failure")):
            self.assertEqual(self.copy_saved_to_slip(selection_id).status_code, 500)
        self.assertEqual(self.db.query(Slip).count(), 0)
        self.assertEqual(self.db.query(SlipItem).count(), 0)
        self.assertIsNotNone(self.db.get(SavedProp, selection_id))

    def test_numeric_price_change_and_even_money_boundary(self):
        item, _ = self.slip_item()
        for original, current, expected in [(-120, -110, "improved"), (-110, -120, "worsened"),
                                             (110, 120, "improved"), (120, 110, "worsened"),
                                             (-100, 100, "unchanged"), (-110, -110, "unchanged")]:
            with self.subTest(original=original, current=current):
                item.original_odds = original
                self.primary.over_odds = current
                self.assertEqual(slip_selection(item, self.prop)["price_change"], expected)

    def test_missing_original_price_is_never_backfilled(self):
        item, _ = self.slip_item()
        item.original_odds = None
        item.original_observed_at = None
        result = slip_selection(item, self.prop)
        self.assertEqual(result["odds"], -110)
        self.assertIsNone(result["original_odds"])
        self.assertIsNone(result["original_observed_at"])
        self.assertIsNone(result["price_change"])

    def test_current_price_requires_identical_book_line_side_and_provider_time(self):
        item, _ = self.slip_item()
        for attribute, value in [("line", 21.5), ("sportsbook", "DraftKings"),
                                 ("over_odds", None), ("provider_observed_at", None)]:
            with self.subTest(attribute=attribute):
                old = getattr(self.primary, attribute)
                setattr(self.primary, attribute, value)
                self.primary.ingested_at = self.now
                result = slip_selection(item, self.prop)
                self.assertIsNone(result["odds"])
                self.assertIsNone(result["price_change"])
                self.assertEqual(result["original_odds"], -115)
                setattr(self.primary, attribute, old)

    def test_game_started_selection_keeps_original_and_is_nonactionable(self):
        item, _ = self.slip_item()
        self.prop.game_time = self.now - timedelta(minutes=1)
        result = slip_selection(item, self.prop)
        self.assertEqual(result["availability"], "game_started")
        self.assertFalse(result["actionable"])
        self.assertIsNone(result["odds"])
        self.assertEqual(result["original_odds"], -115)


class SavedSelectionMigrationTests(unittest.TestCase):
    def test_upgrade_preserves_legacy_rows_without_guessing_and_downgrade_preserves_bookmarks(self):
        spec = importlib.util.spec_from_file_location("saved_selection_revision",
            Path(__file__).parents[1] / "alembic/versions/20261022_05_saved_selections.py")
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE saved_props (id TEXT PRIMARY KEY, user_id TEXT, prop_id TEXT, saved_at DATETIME)"))
            connection.execute(text("CREATE TABLE slip_items (id TEXT PRIMARY KEY, slip_id TEXT, prop_id TEXT, sportsbook TEXT, line FLOAT, side TEXT)"))
            connection.execute(text("INSERT INTO saved_props (id,user_id,prop_id) VALUES ('bookmark','user','prop')"))
            connection.execute(text("INSERT INTO slip_items VALUES ('item','slip','prop','FanDuel',20.5,'under')"))
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade()
            self.assertEqual(connection.execute(text("SELECT sportsbook,line,side,original_odds,original_observed_at FROM saved_props")).one(), (None, None, None, None, None))
            self.assertEqual(connection.execute(text("SELECT id,sportsbook,line,side,original_odds,original_observed_at FROM slip_items")).one(), ("item", "FanDuel", 20.5, "under", None, None))
            connection.execute(text("INSERT INTO saved_props (id,user_id,prop_id,sportsbook,line,side) VALUES ('exact','user','prop','FanDuel',20.5,'over')"))
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade()  # Fresh bootstrap/repeated adoption must not duplicate columns.
            self.assertEqual(connection.execute(text("SELECT id FROM saved_props ORDER BY id")).scalars().all(), ["bookmark", "exact"])
            with Operations.context(MigrationContext.configure(connection)):
                revision.downgrade()
            self.assertEqual(connection.execute(text("SELECT id FROM saved_props")).scalars().all(), ["bookmark"])
            self.assertEqual(connection.execute(text("SELECT id,sportsbook,line,side FROM slip_items")).one(), ("item", "FanDuel", 20.5, "under"))
            self.assertNotIn("original_odds", {column["name"] for column in inspect(connection).get_columns("slip_items")})


if __name__ == "__main__":
    unittest.main()
