"""PostgreSQL equivalence of lightweight reads and their original ORM SELECT."""
from datetime import datetime, timedelta
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import joinedload

import test_ingestion_postgres as fixture
from app.auth import get_optional_user, create_token
from app.database import Base, get_db
from app.models import Event, Player, PlayerGameLog, Prop, PropBook, Interaction, User
from app.routers import props as routes
from app.services.inventory_read_service import read_prop_inventory, read_game_log_inventory
from app.services.trend_service import build_history_research
from app.services.game_log_fields import provider_season


def subject_values(subject):
    def fields(value, model):
        return None if value is None else {column.key: getattr(value, column.key) for column in model.__table__.columns}
    return {"prop": fields(subject, Prop), "player": fields(subject.player, Player),
            "event": fields(subject.event, Event),
            "offers": [fields(offer, PropBook) for offer in subject.book_offers]}


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit isolated PostgreSQL URL unset")
class InventoryReadPostgresTests(unittest.TestCase):
    setUpClass = classmethod(fixture.IngestionPostgresTests.setUpClass.__func__)
    remove_schema = fixture.IngestionPostgresTests.remove_schema

    def setUp(self):
        fixture.IngestionPostgresTests.setUp(self)
        Base.metadata.create_all(self.engine)
        now = datetime.utcnow()
        with self.Session.begin() as db:
            players = [Player(name=f"Read Player {i}", team="Away", team_abbr="AWY", sport="NBA") for i in range(6)]
            events = [Event(provider="the_odds_api", sport_key="basketball_nba", provider_event_id=f"read-{i}",
                            home_team="Home", away_team="Away", scheduled_start_at=now+timedelta(days=2)) for i in range(3)]
            db.add_all(players+events)
            db.flush()
            for i in range(300):
                prop = Prop(player_id=players[i % 6].id, event_id=events[i % 3].id if i % 4 else None,
                            prop_type="points", line=20.5, line_24h_ago=20.5, sportsbook="FanDuel",
                            odds_event_id=f"read-provider-{i}", odds_sport_key="basketball_nba",
                            game_time=now+timedelta(days=2), opponent="Home", is_home=False)
                db.add(prop)
                db.flush()
                if i != 299:
                    db.add_all(PropBook(prop_id=prop.id, sportsbook=book, line=20.5, over_odds=-110,
                                        under_odds=-115, provider_observed_at=now) for book in ("FanDuel", "DraftKings"))
            for player in players:
                db.add_all(PlayerGameLog(player_id=player.id, sport="NBA", source="espn_nba",
                                        external_game_id=f"read-history-{i}", game_date=now-timedelta(days=i+1),
                                        opponent="Home", is_home=False, stats={"points":25}) for i in range(12))
        app = FastAPI()
        app.include_router(routes.router, prefix="/props")
        def database():
            with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_optional_user] = lambda: None
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def query(self, session):
        return session.query(Prop).join(Player).options(
            joinedload(Prop.player), joinedload(Prop.event), joinedload(Prop.book_offers),
        ).filter(Prop.prop_type == "points")

    def test_identical_sql_values_order_identity_sharing_and_clean_session(self):
        captured = []
        def observe(_conn, _cursor, statement, parameters, _context, _many):
            captured.append((statement, parameters))
        event.listen(self.engine, "before_cursor_execute", observe)
        try:
            with self.Session() as db:
                orm = self.query(db).all()
                expected = [subject_values(subject) for subject in orm]
            original_sql = list(captured)
            captured.clear()
            with self.Session() as db:
                projected = read_prop_inventory(self.query(db))
                self.assertEqual([subject_values(subject) for subject in projected], expected)
                self.assertEqual(len(projected), 300)
                self.assertEqual(sum(len(p.book_offers) for p in projected), 598)
                self.assertEqual(len(db.identity_map), 0)
                self.assertFalse(db.new or db.dirty or db.deleted)
                self.assertFalse(any(hasattr(p, "_sa_instance_state") for p in projected))
                self.assertEqual(len({id(p.player) for p in projected}), 6)
                self.assertEqual(len({id(p.event) for p in projected if p.event}), 3)
            self.assertEqual(captured, original_sql)
            self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql, _ in captured))
        finally:
            event.remove(self.engine, "before_cursor_execute", observe)

    def test_duplicate_join_rows_deduplicate_offers_like_orm(self):
        with self.Session() as db:
            expected = [subject_values(p) for p in self.query(db).join(PropBook).all()]
        with self.Session() as db:
            actual = [subject_values(p) for p in read_prop_inventory(self.query(db).join(PropBook))]
        self.assertEqual(actual, expected)

    def test_unrecognized_loader_shape_falls_back_to_orm(self):
        with self.Session() as db:
            query = db.query(Prop).options(joinedload(Prop.player)).filter(Prop.prop_type == "points")
            projected = read_prop_inventory(query)
            self.assertEqual(len(projected), 300)
            self.assertTrue(all(isinstance(prop, Prop) for prop in projected))
            self.assertEqual(len(db.identity_map), 306)
            self.assertFalse(db.new or db.dirty or db.deleted)

    def test_pending_changes_use_original_autoflush_and_remain_rollbackable(self):
        for state in ("new", "dirty", "deleted"):
            with self.subTest(state=state), self.Session() as db:
                target = db.query(Prop).first()
                if state == "new":
                    db.add(Prop(player_id=target.player_id, prop_type="points", line=20.5,
                                sportsbook="FanDuel", odds_event_id="pending-test"))
                elif state == "dirty":
                    target.line = 99.5
                else:
                    db.delete(target)
                subjects = read_prop_inventory(self.query(db))
                self.assertTrue(all(isinstance(subject, Prop) for subject in subjects))
                self.assertEqual(len(subjects), 301 if state == "new" else 299 if state == "deleted" else 300)
                if state == "dirty":
                    self.assertEqual(next(p.line for p in subjects if p.id == target.id), 99.5)
                db.rollback()
        with self.Session() as db:
            self.assertEqual(db.query(Prop).count(), 300)

    def test_feed_discover_ties_and_deep_offsets_match_original_orm(self):
        def collect(route):
            result = []
            for offset in (0, 50, 100, 150, 200, 250, 300, 10000):
                response = self.client.get(f"/props/{route}", params={"limit":50, "offset":offset})
                self.assertEqual(response.status_code, 200)
                body = response.json()
                result.append({"total":body["total"], "rows":[
                    (p["id"], p["rank_score"], p.get("discover_score"), p["trends"])
                    for p in body["props"]]})
            return result
        for route in ("feed", "discover"):
            with self.subTest(route=route):
                # Tied scores retain candidate encounter order. Separate SQL
                # statements without ORDER BY need not encounter rows alike;
                # give both adapters the same deterministic fixture order.
                # Raw SQL/encounter-order parity is tested independently above.
                with patch.object(routes, "read_prop_inventory", side_effect=lambda query:query.order_by(Prop.id).all()):
                    expected = collect(route)
                with patch.object(routes, "read_prop_inventory", side_effect=lambda query:read_prop_inventory(query.order_by(Prop.id))):
                    self.assertEqual(collect(route), expected)
                    self.assertEqual(collect(route), expected)

    def test_log_projection_exact_sql_columns_order_history_and_clean_tracking(self):
        now = datetime.utcnow()
        with self.Session.begin() as db:
            player_id = db.query(Player.id).first()[0]
            db.add_all(PlayerGameLog(player_id=player_id, sport="NBA", source="espn_nba",
                                    external_game_id=f"additional-history-{index}",
                                    game_date=now-timedelta(days=index+20), stats={"points":index % 31},
                                    opponent="Home", is_home=False) for index in range(260))
        columns = tuple(column.key for column in PlayerGameLog.__table__.columns)
        def values(logs):
            return [{key:getattr(log, key) for key in columns} for log in logs]
        def query(db):
            return db.query(PlayerGameLog).filter(PlayerGameLog.sport == "NBA").order_by(PlayerGameLog.game_date.desc())
        captured = []
        def observe(_conn, _cursor, statement, parameters, _context, _many):
            captured.append((statement, parameters))
        event.listen(self.engine, "before_cursor_execute", observe)
        try:
            with self.Session() as db:
                original = query(db).all()
                expected = values(original)
            original_sql = list(captured)
            captured.clear()
            with self.Session() as db:
                projected = read_game_log_inventory(query(db))
                self.assertEqual(values(projected), expected)
                self.assertEqual(len(projected), 332)
                self.assertEqual(len(db.identity_map), 0)
                self.assertFalse(db.new or db.dirty or db.deleted)
                self.assertFalse(any(hasattr(log, "_sa_instance_state") for log in projected))
            self.assertEqual(captured, original_sql)
            self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql, _ in captured))
        finally:
            event.remove(self.engine, "before_cursor_execute", observe)
        for line in (0, 20.5, 25, 50):
            self.assertEqual(build_history_research("NBA", "points", line, provider_season("NBA", now),
                [log for log in projected if log.player_id == player_id], now=now),
                build_history_research("NBA", "points", line, provider_season("NBA", now),
                [log for log in original if log.player_id == player_id], now=now))

    def test_log_empty_and_unknown_shape_fallback(self):
        with self.Session() as db:
            self.assertEqual(read_game_log_inventory(db.query(PlayerGameLog).filter(PlayerGameLog.sport == "unavailable")), [])
            self.assertEqual(len(db.identity_map), 0)
            query = db.query(PlayerGameLog).options(joinedload(PlayerGameLog.player)).order_by(PlayerGameLog.game_date.desc())
            logs = read_game_log_inventory(query)
            self.assertEqual(len(logs), 72)
            self.assertTrue(all(isinstance(log, PlayerGameLog) for log in logs))
            self.assertEqual(len(db.identity_map), 78)

    def test_log_pending_fallback_retains_autoflush_and_rollback(self):
        with self.Session() as db:
            log = db.query(PlayerGameLog).first()
            log.stats = {"points":99}
            logs = read_game_log_inventory(db.query(PlayerGameLog).order_by(PlayerGameLog.game_date.desc()))
            self.assertTrue(all(isinstance(item, PlayerGameLog) for item in logs))
            self.assertEqual(next(item.stats for item in logs if item.id == log.id), {"points":99})
            db.rollback()
        with self.Session() as db:
            self.assertTrue(all(log.stats != {"points":99} for log in db.query(PlayerGameLog).all()))

    def test_log_multiplying_join_deduplicates_identity_in_original_order(self):
        def query(db):
            return db.query(PlayerGameLog).join(Prop, Prop.player_id == PlayerGameLog.player_id).order_by(PlayerGameLog.game_date.desc())
        with self.Session() as db:
            original = query(db).all()
            expected = [{column.key:getattr(log, column.key) for column in PlayerGameLog.__table__.columns}
                        for log in original]
        with self.Session() as db:
            projected = read_game_log_inventory(query(db))
            self.assertEqual([{column.key:getattr(log, column.key) for column in PlayerGameLog.__table__.columns}
                              for log in projected], expected)
            self.assertEqual(len(projected), 72)
            self.assertEqual(len(db.identity_map), 0)

    def test_personalized_feed_interactions_are_bounded_and_match_orm_ranks(self):
        with self.Session.begin() as db:
            user = User(email="personalized-inventory@example.invalid", hashed_password="unused",
                        fav_sports=["NBA"], fav_prop_types=["points"])
            db.add(user)
            db.flush()
            for index, prop in enumerate(db.query(Prop).limit(30).all()):
                player = Player(name=f"Interaction Player {index}", team="Away", team_abbr="AWY", sport="NBA")
                db.add(player)
                db.flush()
                prop.player_id = player.id
                db.add(Interaction(user_id=user.id, prop_id=prop.id, action="view"))
            token = create_token(user.id)
        self.client.app.dependency_overrides.pop(get_optional_user)
        captured = []
        def observe(_conn, _cursor, statement, _params, _context, _many):
            captured.append(statement)
        def request():
            response = self.client.get("/props/feed?limit=20", headers={"Authorization":"Bearer "+token})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            return {"total":body["total"], "props":[
                (prop["id"], prop["rank_score"], prop["reasons"], prop["fatigue"], prop["trends"])
                for prop in body["props"]]}
        with patch.object(routes, "read_prop_inventory", side_effect=lambda query:query.all()):
            expected = request()
        event.listen(self.engine, "before_cursor_execute", observe)
        try:
            self.assertEqual(request(), expected)
        finally:
            event.remove(self.engine, "before_cursor_execute", observe)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql in captured))
        self.assertLessEqual(len(captured), 8, f"30 interactions used {len(captured)} SQL statements")
