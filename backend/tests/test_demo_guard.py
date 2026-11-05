import os
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.engine import make_url

from app.models import Prop, PropBook, PropBookSnapshot, PlayerGameLog, FatigueScore
from app.services.demo_guard import (
    DemoOperationRefused, require_demo_dataset, require_demo_environment,
)
from scripts.refresh_demo_data import refresh_props, refresh_fatigue
from scripts.update_line_movement import apply_line_shifts
import seed
from scripts import refresh_demo_data, update_line_movement


def demo_prop(**overrides):
    values = dict(odds_event_id="demo:player", odds_sport_key="demo",
                  sportsbook="Demo", odds_last_seen_at=None, player_id="player",
                  line=20.5, line_24h_ago=20.0, popularity_count=2, is_active=True,
                  game_time=None)
    values.update(overrides)
    return SimpleNamespace(**values)


def session(props=None, present=None, url="postgresql://localhost/proppulse_demo"):
    """Pure session stand-in: never creates an engine or connects to any DB."""
    db = MagicMock()
    db.new = db.dirty = db.deleted = set()
    db.get_bind.return_value = SimpleNamespace(url=make_url(url))
    db.no_autoflush = nullcontext()
    rows = {Prop: props or [], FatigueScore: []}
    if present:
        rows[present] = [SimpleNamespace()]

    def query(model):
        result = MagicMock()
        result.first.return_value = next(iter(rows.get(model, [])), None)
        result.all.return_value = rows.get(model, [])
        result.filter.return_value = result
        return result

    db.query.side_effect = query
    return db


class DemoGuardTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"PROPPULSE_DEMO_MODE": "true"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_opt_in_required_before_reading_or_mutating_database(self):
        for mode in ("", "false", "1"):
            with self.subTest(mode=mode), patch.dict(os.environ, {"PROPPULSE_DEMO_MODE": mode}):
                db = session([demo_prop()])
                with self.assertRaisesRegex(DemoOperationRefused, "DEMO_MODE"):
                    require_demo_dataset(db)
                db.query.assert_not_called()
                db.commit.assert_not_called()

    def test_live_or_ambiguous_database_names_and_dialects_refused(self):
        for url in ("postgresql://localhost/proppulse", "postgresql://localhost/production_demo",
                    "sqlite:///:memory:", "postgresql://localhost/proppulse_demo_backup"):
            with self.subTest(url=url):
                db = session(url=url)
                with self.assertRaises(DemoOperationRefused):
                    require_demo_dataset(db)
                db.query.assert_not_called()

    def test_provider_and_unmarked_props_refuse_all_mutating_helpers(self):
        for changes in ({"odds_event_id": "real-provider-event"}, {"odds_event_id": None},
                        {"odds_sport_key": "basketball_nba"}, {"sportsbook": "FanDuel"},
                        {"odds_last_seen_at": "observed"}):
            for helper in (refresh_props, refresh_fatigue, apply_line_shifts):
                with self.subTest(changes=changes, helper=helper.__name__):
                    safe = demo_prop()
                    unsafe = demo_prop(**changes)
                    db = session([safe, unsafe])
                    with self.assertRaisesRegex(DemoOperationRefused, "unmarked"):
                        helper(db)
                    self.assertEqual(safe.line, 20.5)
                    self.assertIsNone(safe.game_time)
                    db.commit.assert_not_called()

    def test_any_offer_snapshot_or_history_blocks_even_marked_demo_props(self):
        for model in (PropBook, PropBookSnapshot, PlayerGameLog):
            with self.subTest(model=model):
                db = session([demo_prop()], present=model)
                with self.assertRaisesRegex(DemoOperationRefused, "history"):
                    apply_line_shifts(db)
                db.commit.assert_not_called()

    def test_schema_verification_failure_is_fail_closed(self):
        db = session()
        db.query.side_effect = RuntimeError("missing schema")
        with self.assertRaisesRegex(DemoOperationRefused, "could not be verified"):
            refresh_props(db)
        db.commit.assert_not_called()

    def test_pending_changes_are_not_flushed_by_guard(self):
        db = session([demo_prop()])
        db.dirty = {object()}
        with self.assertRaisesRegex(DemoOperationRefused, "pending writes"):
            require_demo_dataset(db)
        db.query.assert_not_called()
        db.flush.assert_not_called()

    def test_uncertain_fatigue_data_is_refused(self):
        db = session()
        original = db.query.side_effect

        def query(model):
            result = original(model)
            if model is FatigueScore:
                result.all.return_value = [SimpleNamespace(player_id="unverified")]
            return result

        db.query.side_effect = query
        with self.assertRaisesRegex(DemoOperationRefused, "fatigue records"):
            refresh_fatigue(db)
        db.commit.assert_not_called()

    def test_explicit_demo_rows_are_eligible_for_helpers(self):
        for helper in (refresh_props, refresh_fatigue, apply_line_shifts):
            with self.subTest(helper=helper.__name__):
                prop = demo_prop()
                db = session([prop])
                with patch("random.choice", side_effect=lambda values: values[0]):
                    helper(db)
                db.commit.assert_called_once()
                self.assertEqual(prop.odds_event_id, "demo:player")
                self.assertIsNone(prop.odds_last_seen_at)

    def test_real_matchup_context_is_not_accepted_by_demo_helper(self):
        db = session([demo_prop()])
        with self.assertRaisesRegex(DemoOperationRefused, "matchup"):
            apply_line_shifts(db, [{"id": "real-event"}])
        db.commit.assert_not_called()

    def test_seed_entry_points_refuse_without_explicit_mode_before_db_access(self):
        with patch.dict(os.environ, {"PROPPULSE_DEMO_MODE": "false"}), \
                patch.object(seed, "SessionLocal") as factory, \
                patch.object(seed.Base.metadata, "create_all") as create:
            for helper in (seed.create_tables, seed.seed):
                with self.assertRaises(DemoOperationRefused):
                    helper()
            factory.assert_not_called()
            create.assert_not_called()

    def test_demo_cli_entry_points_refuse_before_opening_sessions(self):
        for module in (refresh_demo_data, update_line_movement):
            with self.subTest(module=module.__name__), \
                    patch.dict(os.environ, {"PROPPULSE_DEMO_MODE": "false"}), \
                    patch.object(module, "SessionLocal") as factory:
                with self.assertRaises(DemoOperationRefused):
                    module.main()
                factory.assert_not_called()

    def test_movement_main_uses_only_demo_data_and_no_provider_requests(self):
        db = session([demo_prop()])
        with patch.object(update_line_movement, "engine", db.get_bind()), \
                patch.object(update_line_movement, "SessionLocal", return_value=db), \
                patch("httpx.Client", side_effect=AssertionError("No external client allowed")), \
                patch("builtins.print"):
            update_line_movement.main()
        db.commit.assert_called_once()
        db.close.assert_called_once()

    def test_seed_never_resets_nonempty_demo_database(self):
        db = session([demo_prop()])
        with patch.object(seed, "engine", db.get_bind()), \
                patch.object(seed, "SessionLocal", return_value=db):
            with self.assertRaisesRegex(DemoOperationRefused, "not empty"):
                seed.seed()
        db.commit.assert_not_called()
        db.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
