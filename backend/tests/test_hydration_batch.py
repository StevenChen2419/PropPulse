"""Real isolated PostgreSQL hydration budgets, selection fidelity and no writes."""
from datetime import datetime, timedelta
import hashlib
import json
import os
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

import test_ingestion_postgres as fixture
from app.auth import create_token
from app.database import Base, get_db
from app.models import Event, Player, Prop, PropBook, SavedProp, Slip, SlipItem, User
from app.routers.users import user_router
from app.routers import users as routes


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit isolated PostgreSQL URL unset")
class HydrationBatchPostgresTests(unittest.TestCase):
    setUpClass = classmethod(fixture.IngestionPostgresTests.setUpClass.__func__)
    remove_schema = fixture.IngestionPostgresTests.remove_schema

    def setUp(self):
        fixture.IngestionPostgresTests.setUp(self)
        Base.metadata.create_all(self.engine)
        now = datetime.utcnow()
        with self.Session.begin() as db:
            users = [User(email=f"batch-{n}@example.invalid", hashed_password="unused") for n in range(2)]
            db.add_all(users)
            db.flush()
            ev = Event(provider="the_odds_api", sport_key="basketball_nba", provider_event_id="batch-event",
                       home_team="Home", away_team="Away", scheduled_start_at=now + timedelta(days=2))
            db.add(ev)
            db.flush()
            self.prop_ids = []
            self.saved_ids = []
            self.item_ids = []
            self.expected = {}
            slips = [Slip(user_id=user.id) for user in users]
            db.add_all(slips)
            db.flush()
            for n in range(40):
                player = Player(name=f"Batch Player {n}", team="Away", team_abbr="AWY", sport="NBA")
                db.add(player)
                db.flush()
                prop = Prop(player_id=player.id, event_id=ev.id if n % 2 else None, prop_type="points",
                            line=20.5, sportsbook="FanDuel", odds_event_id=f"batch-provider-{n}",
                            odds_sport_key="basketball_nba", game_time=now + timedelta(days=2),
                            is_home=False, opponent="Home")
                db.add(prop)
                db.flush()
                # A better current primary price must never replace the stored
                # DraftKings Under 19.5 selection, even when that selection expires.
                db.add(PropBook(prop_id=prop.id, sportsbook="FanDuel", line=20.5,
                                over_odds=150, under_odds=160,
                                provider_observed_at=now if n % 3 else now - timedelta(hours=7)))
                if n % 4 != 3:
                    db.add(PropBook(prop_id=prop.id, sportsbook="DraftKings", line=19.5,
                                    over_odds=-105, under_odds=-120,
                                    provider_observed_at=now if n % 4 != 2 else now - timedelta(hours=7)))
                self.prop_ids.append(prop.id)
                self.expected[prop.id] = (n % 4, bool(prop.event_id))
                if n < 20:
                    saved = SavedProp(user_id=users[0].id, prop_id=prop.id)
                    db.add(saved)
                    db.flush()
                    self.saved_ids.append(prop.id)
                if n < 10:
                    item = SlipItem(slip_id=slips[0].id, prop_id=prop.id, side="under",
                                    sportsbook="DraftKings", line=19.5)
                    db.add(item)
                    db.flush()
                    self.item_ids.append(item.id)
            other = SavedProp(user_id=users[1].id, prop_id=self.prop_ids[-1])
            db.add_all([other, SlipItem(slip_id=slips[1].id, prop_id=self.prop_ids[-1], side="over",
                                      sportsbook="FanDuel", line=20.5)])
            self.user_id, self.other_id = [user.id for user in users]
            self.slip_id = slips[0].id
        app = FastAPI()
        app.include_router(user_router, prefix="/users")
        def database():
            with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer " + create_token(self.user_id)}

    def fingerprint(self):
        rows = {}
        with self.engine.connect() as conn:
            for table in Base.metadata.sorted_tables:
                rows[table.name] = [dict(row) for row in conn.execute(select(table).order_by(table.c.id)).mappings()]
        return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()

    def request(self, route, headers=None):
        statements = []
        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        before = self.fingerprint()
        event.listen(self.engine, "before_cursor_execute", observe)
        try:
            response = self.client.get("/users/me/" + route, headers=headers or self.headers)
        finally:
            event.remove(self.engine, "before_cursor_execute", observe)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql in statements), statements)
        self.assertEqual(self.fingerprint(), before)
        return response.json(), len(statements)

    def test_saved_scoped_batch_budget_and_growth(self):
        body, small = self.request("saved")
        self.assertEqual([prop["id"] for prop in body["saved"]], self.saved_ids)
        with self.Session.begin() as db:
            db.add_all(SavedProp(user_id=self.user_id, prop_id=prop_id) for prop_id in self.prop_ids[20:])
        body, large = self.request("saved")
        self.assertEqual([prop["id"] for prop in body["saved"]], self.prop_ids)
        other, _ = self.request("saved", {"Authorization": "Bearer " + create_token(self.other_id)})
        self.assertEqual([prop["id"] for prop in other["saved"]], [self.prop_ids[-1]])
        self.assertLessEqual(small, 10, f"20 saved items used {small} SQL statements")
        self.assertLessEqual(large, 10, f"40 saved items used {large} SQL statements")
        self.assertLessEqual(large - small, 2)

    def test_slip_exact_selection_batch_budget_and_growth(self):
        body, small = self.request("slip")
        self.assertEqual([item["id"] for item in body["slip"]["items"]], self.item_ids)
        with self.Session.begin() as db:
            for prop_id in self.prop_ids[10:20]:
                item = SlipItem(slip_id=self.slip_id, prop_id=prop_id, side="under",
                                sportsbook="DraftKings", line=19.5)
                db.add(item)
                db.flush()
                self.item_ids.append(item.id)
        body, large = self.request("slip")
        self.assertEqual([item["id"] for item in body["slip"]["items"]], self.item_ids)
        for item in body["slip"]["items"]:
            self.assertEqual(item["side"], "under")
            selection = item["selection"]
            self.assertEqual((selection["sportsbook"], selection["line"]), ("DraftKings", 19.5))
            variant, linked = self.expected[item["prop_id"]]
            self.assertEqual(item["prop"]["event_id"] is not None, linked)
            self.assertEqual(selection["actionable"], variant in (0, 1))
            self.assertEqual(selection["odds"], -120 if variant in (0, 1) else None)
        other, _ = self.request("slip", {"Authorization": "Bearer " + create_token(self.other_id)})
        self.assertEqual(len(other["slip"]["items"]), 1)
        self.assertEqual(other["slip"]["items"][0]["prop_id"], self.prop_ids[-1])
        self.assertLessEqual(small, 10, f"10 slip items used {small} SQL statements")
        self.assertLessEqual(large, 10, f"20 slip items used {large} SQL statements")
        self.assertLessEqual(large - small, 2)

    def test_casefold_book_ties_preserve_original_lazy_collection_order(self):
        with self.Session.begin() as db:
            db.add_all(PropBook(prop_id=prop_id, sportsbook="FANDUEL", line=20.5,
                               over_odds=150, under_odds=160,
                               provider_observed_at=datetime.utcnow()) for prop_id in self.prop_ids)
        def normalized(props):
            return [(prop["id"], prop["best_over"], prop["best_under"],
                     [offer["sportsbook"] for offer in prop["sportsbook_offers"]]) for prop in props]
        # This legitimate planner choice exposes a joined eager collection order
        # differing from the original per-prop lazy query. The setting applies
        # only to these disposable transactions and is rolled back on close.
        with self.Session() as db:
            db.execute(text("SET LOCAL enable_hashjoin=off"))
            saved = db.query(SavedProp).filter(SavedProp.user_id == self.user_id).all()
            expected_saved = normalized([routes._prop_out(db.query(Prop).join(Player).filter(Prop.id == row.prop_id).first(), None)
                                         for row in saved])
        with self.Session() as db:
            db.execute(text("SET LOCAL enable_hashjoin=off"))
            items = db.query(SlipItem).filter(SlipItem.slip_id == self.slip_id).all()
            expected_slip = normalized([routes._prop_out(db.query(Prop).join(Player).filter(Prop.id == row.prop_id).first(), None)
                                        for row in items])
        with self.Session() as db:
            db.execute(text("SET LOCAL enable_hashjoin=off"))
            user = db.get(User, self.user_id)
            self.assertEqual(normalized(routes.get_saved(user=user, db=db)["saved"]), expected_saved)
        with self.Session() as db:
            db.execute(text("SET LOCAL enable_hashjoin=off"))
            user = db.get(User, self.user_id)
            response = routes.get_slip(user=user, db=db)
            self.assertEqual(normalized([item["prop"] for item in response["slip"]["items"]]), expected_slip)
