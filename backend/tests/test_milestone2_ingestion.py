"""Isolated regression fixtures: no application DB, real HTTP, or app lifespan.

SQLite verifies SQLAlchemy persistence/rollback only. Advisory-lock tests assert
connection ownership with mocks and are not PostgreSQL integration evidence.
"""
import copy
import unittest
from uuid import uuid4
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Event, Player, Prop, PropBook, PropBookSnapshot, SavedProp, Slip, SlipItem
from app.services.ingestion_control import RequestBudget, odds_ingestion_lock
from app.services.odds_parser import parse_event
from scripts import fetch_odds as ingestion

NBA = "basketball_nba"
MLB = "baseball_mlb"
NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
OBSERVED = NOW - timedelta(minutes=5)
START = NOW + timedelta(hours=5)


def event(event_id="event-1"):
    return dict(id=event_id, sport_key=NBA, commence_time=START.isoformat() + "Z",
                home_team="Home Team", away_team="Away Team")


def payload(event_id="event-1", key="fanduel", title="FanDuel", name="Test Player", line=20.5):
    return {**event(event_id), "bookmakers": [{"key": key, "title": title,
        "last_update": OBSERVED.isoformat() + "Z", "markets": [{
            "key": "player_points", "last_update": OBSERVED.isoformat() + "Z",
            "outcomes": [{"name": "Over", "description": name, "point": line, "price": -110},
                         {"name": "Under", "description": name, "point": line, "price": -105}]}]}]}


def parsed(**kwargs):
    data = payload(**kwargs)
    return parse_event(data, event(data["id"]), NBA, ingestion.SPORT_CONFIG[NBA], NOW)[0]


def response(status=200, data=None, headers=None):
    result = MagicMock(status_code=status, headers=headers or {})
    result.json.return_value = data
    return result


class ParserCoverageTests(unittest.TestCase):
    def test_realistic_pair_preserves_market_observation_and_stable_key(self):
        rows = parsed()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider_observed_at"], OBSERVED)
        self.assertEqual(rows[0]["provider_bookmaker_key"], "fanduel")
        self.assertEqual((rows[0]["over_odds"], rows[0]["under_odds"]), (-110, -105))

    def test_missing_mismatched_and_ambiguous_events_have_no_rows(self):
        missing = payload()
        missing.pop("id")
        empty_books = {**payload(), "bookmakers": []}
        empty_markets = payload()
        empty_markets["bookmakers"][0]["markets"] = []
        for data in (None, missing, payload(event_id="different"), empty_books, empty_markets):
            with self.subTest(data=data):
                rows, issues = parse_event(data, event(), NBA, ingestion.SPORT_CONFIG[NBA], NOW)
                self.assertEqual(rows, [])
                self.assertTrue(issues)

    def test_missing_invalid_and_future_timestamps_do_not_fabricate_observation(self):
        for timestamp in (None, "invalid", NOW.isoformat(), (NOW + timedelta(hours=1)).isoformat() + "Z"):
            with self.subTest(timestamp=timestamp):
                data = payload()
                data["bookmakers"][0]["markets"][0]["last_update"] = timestamp
                rows, issues = parse_event(data, event(), NBA, ingestion.SPORT_CONFIG[NBA], NOW)
                self.assertIsNone(rows[0]["provider_observed_at"])
                self.assertIn("missing_or_invalid_observation", issues)

    def test_unpaired_different_lines_and_conflicting_prices_are_rejected(self):
        cases = []
        unpaired = payload()
        unpaired["bookmakers"][0]["markets"][0]["outcomes"].pop()
        cases.append(unpaired)
        different_line = payload()
        different_line["bookmakers"][0]["markets"][0]["outcomes"][1]["point"] = 21.5
        cases.append(different_line)
        conflict = payload()
        conflict["bookmakers"][0]["markets"][0]["outcomes"].append(
            {"name": "Over", "description": "Test Player", "point": 20.5, "price": 120})
        cases.append(conflict)
        for data in cases:
            rows, issues = parse_event(data, event(), NBA, ingestion.SPORT_CONFIG[NBA], NOW)
            self.assertEqual(rows, [])
            self.assertTrue(issues)

    def test_one_failed_event_preserves_successful_event_rows_and_coverage(self):
        status = ingestion.make_sport_status(NBA)
        with patch.object(ingestion, "get", side_effect=[(200, payload(), {}), (500, {}, {})]), \
                patch.object(ingestion.time, "sleep"), patch("builtins.print"):
            rows = ingestion.fetch_player_props(None, NBA, [event(), event("event-2")], status)
        self.assertEqual(len(rows), 1)
        self.assertEqual(status["market_requests_failed"], 1)
        self.assertEqual(status["event_coverage"]["event-2"]["status"], "failed")

    def test_event_loop_stops_immediately_and_counts_unrequested_events_as_skipped(self):
        status = ingestion.make_sport_status(NBA)
        client = MagicMock()
        client.get.return_value = MagicMock(status_code=200, headers={}, json=lambda: payload())
        budget = RequestBudget(max_requests=1, max_credits=100, reserve=0)
        with patch.object(ingestion, "ACTIVE_BUDGET", budget), patch.object(ingestion.time, "sleep") as sleep, patch("builtins.print"):
            rows = ingestion.fetch_player_props(client, NBA, [event(), event("event-2"), event("event-3")], status)
        self.assertEqual(len(rows), 1)
        self.assertEqual(client.get.call_count, 1)
        self.assertEqual(status["market_requests_made"], 1)
        self.assertEqual(status["events_skipped"], 2)
        sleep.assert_not_called()

    def test_parser_exception_does_not_authorize_offer_replacement(self):
        status = ingestion.make_sport_status(NBA)
        with patch.object(ingestion, "get", return_value=(200, payload(), {})), \
                patch.object(ingestion, "parse_event", side_effect=[ValueError("bad payload"), (parsed(), [])]), \
                patch.object(ingestion.time, "sleep"), patch("builtins.print"):
            rows = ingestion.fetch_player_props(None, NBA, [event(), event("event-2")], status)
        self.assertEqual(len(rows), 1)
        self.assertEqual(status["market_requests_failed"], 1)
        self.assertEqual(status["event_coverage"][event()["id"]]["status"], "parse_failed")
        self.assertFalse(ingestion.should_replace_all_offers(rows, status))



class IsolatedPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine, tables=[model.__table__ for model in
            (Event, Player, Prop, PropBook, PropBookSnapshot, SavedProp, Slip, SlipItem)])
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.factory()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.quiet = patch("builtins.print")
        self.quiet.start()
        self.addCleanup(self.quiet.stop)

    def apply(self, rows=None, sport=NBA, status=None):
        status = status or ingestion.make_sport_status(sport)
        # Missing players require a unique, event-verified roster identity.
        roster = {ingestion.normalize_name(row["player_name"]):
                  {"team": row["home_team"], "team_abbr": "HOM"} for row in rows or []}
        result = ingestion.apply_updates_for_sport(self.db, sport, rows or [], status, roster)
        self.db.commit()
        return result, status

    def bootstrap(self):
        self.apply(parsed())
        return self.db.query(Prop).one(), self.db.query(PropBook).one()

    def test_complete_refresh_creates_one_prop_offer_snapshot_and_valid_observation(self):
        prop, offer = self.bootstrap()
        self.assertEqual(self.db.query(Player).count(), 1)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)
        self.assertEqual(prop.odds_event_id, "event-1")
        self.assertEqual(offer.provider_observed_at, OBSERVED)
        self.assertGreater(offer.ingested_at, offer.provider_observed_at)
        self.assertEqual(offer.provider_bookmaker_key, "fanduel")
        self.assertEqual(self.apply(parsed())[1]["availability"], "live")

    def test_identical_repeat_has_no_duplicate_or_snapshot_churn(self):
        prop, offer = self.bootstrap()
        prop_id, offer_id = prop.id, offer.id
        result, _ = self.apply(parsed())
        self.assertEqual(self.db.query(Prop).one().id, prop_id)
        self.assertEqual(self.db.query(PropBook).one().id, offer_id)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)
        self.assertEqual(result["sportsbook_snapshots_saved"], 0)
        self.assertEqual(offer.provider_observed_at, OBSERVED)

    def test_successful_write_of_stale_observation_reports_last_known(self):
        rows = parsed()
        rows[0]["provider_observed_at"] = NOW - timedelta(hours=2)
        _, status = self.apply(rows)
        self.assertEqual(status["availability"], "last_known")
        prop = self.db.query(Prop).one()
        decision = ingestion.offer_availability(prop, "FanDuel", prop.line, "over", NOW)
        self.assertFalse(decision["actionable"])
        self.assertEqual(decision["source"], "last_known")
        self.assertEqual(decision["odds"], -110)
        self.assertEqual(status["cached_live_props"], 0)

    def test_mixed_live_and_last_known_status_preserves_per_offer_actionability(self):
        rows = parsed() + parsed(name="Second Test Player")
        rows[1]["provider_observed_at"] = NOW - timedelta(hours=2)
        _, status = self.apply(rows)
        self.assertEqual(status["availability"], "last_known")
        decisions = [ingestion.offer_availability(prop, "FanDuel", prop.line, "over", NOW)
                     for prop in self.db.query(Prop).all()]
        self.assertEqual(sorted(d["availability"] for d in decisions), ["available", "last_known"])
        self.assertEqual(sum(d["actionable"] for d in decisions), 1)

    def test_successful_write_of_missing_observation_reports_unavailable(self):
        rows = parsed()
        rows[0]["provider_observed_at"] = None
        _, status = self.apply(rows)
        self.assertEqual(status["availability"], "unavailable")

    def test_successful_write_of_expired_observation_reports_unavailable(self):
        rows = parsed()
        rows[0]["provider_observed_at"] = NOW - timedelta(hours=7)
        _, status = self.apply(rows)
        self.assertEqual(status["availability"], "unavailable")

    def test_preserved_cache_age_uses_provider_observation_not_local_write_time(self):
        self.bootstrap()
        _, status = self.apply([])
        self.assertEqual(status["cached_at"], OBSERVED.replace(tzinfo=timezone.utc).isoformat())
        self.assertGreaterEqual(status["cache_age_minutes"], 5)

    def test_event_discovery_http_failure_is_failed_and_not_no_games_success(self):
        status = ingestion.make_sport_status(NBA)
        status["active"] = True
        with patch.object(ingestion, "get", return_value=(500, {}, {})):
            self.assertEqual(ingestion.fetch_events(None, NBA, status), [])
        with patch.object(ingestion, "SPORT_CONFIG", {NBA: ingestion.SPORT_CONFIG[NBA]}), \
                patch.object(ingestion, "SessionLocal", self.factory):
            ingestion.persist_sports({NBA: status}, {NBA: []}, {})
        self.assertEqual(status["outcome"], "failed")
        self.assertEqual(status["availability"], "unavailable")

    def test_market_and_bookmaker_omission_preserves_existing_offers_and_history(self):
        self.apply(parsed() + parsed(key="draftkings", title="DraftKings"))
        existing = {offer.sportsbook: offer.id for offer in self.db.query(PropBook)}
        self.apply(parsed(line=21.5))
        self.assertEqual({offer.sportsbook: offer.id for offer in self.db.query(PropBook)}, existing)
        draftkings = self.db.query(PropBook).filter_by(sportsbook="DraftKings").one()
        self.assertEqual(draftkings.line, 20.5)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 3)

    def test_failed_missing_and_empty_refresh_preserve_offer_values(self):
        prop, offer = self.bootstrap()
        saved = (prop.id, prop.game_time, offer.id, offer.line, offer.provider_observed_at)
        for coverage in ({"status": "failed"}, {"status": "partial", "issues": ["ambiguous_empty_markets"]}, {}):
            status = ingestion.make_sport_status(NBA)
            status["event_coverage"] = {"event-1": coverage}
            self.apply([], status=status)
            self.assertEqual((prop.id, prop.game_time, offer.id, offer.line, offer.provider_observed_at), saved)
            self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)

    def test_stable_key_title_change_preserves_offer_and_selection_title(self):
        _, offer = self.bootstrap()
        old_id = offer.id
        self.apply(parsed(title="FanDuel New Display Title"))
        self.assertEqual(self.db.query(PropBook).count(), 1)
        self.assertEqual(offer.id, old_id)
        self.assertEqual(offer.sportsbook, "FanDuel")
        self.assertEqual(offer.provider_title, "FanDuel New Display Title")

    def test_reliable_legacy_alias_is_adopted_without_duplicate(self):
        _, offer = self.bootstrap()
        offer.provider_bookmaker_key = None
        self.db.commit()
        old_id = offer.id
        self.apply(parsed())
        self.assertEqual(self.db.query(PropBook).one().id, old_id)
        self.assertEqual(offer.provider_bookmaker_key, "fanduel")

    def test_older_or_missing_observation_cannot_replace_known_offer(self):
        _, offer = self.bootstrap()
        for observed in (None, OBSERVED - timedelta(hours=1)):
            rows = parsed(line=99.5)
            rows[0]["provider_observed_at"] = observed
            self.apply(rows)
            self.assertEqual(offer.line, 20.5)
            self.assertEqual(offer.provider_observed_at, OBSERVED)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)

    def test_ambiguous_duplicate_player_identity_preserves_old_offer(self):
        self.bootstrap()
        self.db.add(Player(name="Test Player", team="Other", team_abbr="OTH", sport="NBA"))
        self.db.commit()
        result, _ = self.apply(parsed(line=99.5))
        self.assertGreater(result["unmatched_outcomes"], 0)
        self.assertEqual(self.db.query(PropBook).one().line, 20.5)
        self.assertEqual(self.db.query(Prop).count(), 1)

    def test_duplicate_alternate_lines_for_one_book_are_ambiguous_and_preserved(self):
        self.bootstrap()
        self.apply(parsed(line=21.5) + parsed(line=22.5))
        self.assertEqual(self.db.query(PropBook).one().line, 20.5)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)

    def test_failure_before_commit_rolls_back_prepared_updates_and_snapshots(self):
        self.bootstrap()
        status = ingestion.make_sport_status(NBA)
        ingestion.apply_updates_for_sport(self.db, NBA, parsed(line=99.5), status)
        self.db.flush()
        self.db.rollback()
        self.assertEqual(self.db.query(PropBook).one().line, 20.5)
        self.assertEqual(self.db.query(Prop).one().line, 20.5)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)

    def test_saved_prop_and_exact_slip_choice_survive_missing_and_changed_offer(self):
        # User IDs are inert fixture IDs. SQLite does not prove PostgreSQL FK behavior.
        prop, _ = self.bootstrap()
        user_id = str(uuid4())
        saved = SavedProp(user_id=user_id, prop_id=prop.id)
        slip = Slip(user_id=user_id)
        self.db.add_all([saved, slip])
        self.db.flush()
        item = SlipItem(slip_id=slip.id, prop_id=prop.id, sportsbook="FanDuel", line=20.5, side="under")
        self.db.add(item)
        self.db.commit()
        identities = (saved.id, item.id, item.prop_id, item.sportsbook, item.line, item.side)
        self.apply([])
        self.apply(parsed(line=21.5))
        self.db.expire_all()
        saved, item = self.db.query(SavedProp).one(), self.db.query(SlipItem).one()
        self.assertEqual((saved.id, item.id, item.prop_id, item.sportsbook, item.line, item.side), identities)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 2)

    def test_sport_transaction_failure_rolls_back_and_next_sport_commits(self):
        self.bootstrap()
        statuses = {key: ingestion.make_sport_status(key) for key in (NBA, MLB)}
        for status in statuses.values():
            status["active"] = True
        mlb = {**parsed()[0], "sport": "MLB", "sport_key": MLB,
               "event_id": "mlb-event", "player_name": "Baseball Player", "prop_type": "hits"}
        first, second = self.factory(), self.factory()
        with patch.object(ingestion, "SPORT_CONFIG", {key: ingestion.SPORT_CONFIG[key] for key in (NBA, MLB)}), \
                patch.object(ingestion, "SessionLocal", side_effect=[first, second]), \
                patch.object(first, "commit", side_effect=RuntimeError("commit failed")):
            ingestion.persist_sports(statuses, {NBA: parsed(line=99.5), MLB: [mlb]},
                {MLB: {"baseball player": {"team": mlb["home_team"], "team_abbr": "HOM"}}})
        self.db.expire_all()
        self.assertEqual(statuses[NBA]["outcome"], "failed")
        self.assertEqual(statuses[NBA]["sportsbook_offers_saved"], 0)
        self.assertEqual(statuses[NBA]["matching_diagnostics"]["transaction_outcome"], "rolled_back")
        self.assertEqual(statuses[NBA]["matching_diagnostics"]["row_counts"], {"matched": 1})
        self.assertEqual(statuses[MLB]["outcome"], "completed")
        self.assertEqual(statuses[MLB]["matching_diagnostics"]["transaction_outcome"], "committed")
        self.assertEqual(statuses[NBA]["event_relationships"]["committed"]["events_reused"], 0)
        self.assertEqual(statuses[NBA]["event_relationships"]["rolled_back"]["events_reused"], 1)
        self.assertEqual(statuses[MLB]["event_relationships"]["committed"]["events_created"], 1)
        self.assertEqual(self.db.query(PropBook).join(Prop).filter(Prop.odds_event_id == "event-1").one().line, 20.5)
        self.assertEqual(self.db.query(Prop).filter_by(odds_event_id="mlb-event").count(), 1)


class BudgetAndLockTests(unittest.TestCase):
    def test_budget_exhaustion_never_makes_an_extra_http_attempt(self):
        budget = RequestBudget(max_requests=1, max_credits=100, reserve=0)
        client = MagicMock()
        client.get.return_value = response(200, {})
        with patch.object(ingestion, "ACTIVE_BUDGET", budget):
            self.assertEqual(ingestion.get(client, "/fake", {})[0], 200)
            self.assertEqual(ingestion.get(client, "/fake", {})[0], 0)
            self.assertEqual(ingestion.get(client, "/fake", {})[0], 0)
        self.assertEqual(client.get.call_count, 1)
        self.assertTrue(budget.stopped)

    def test_credit_budget_reserved_before_paid_market_request(self):
        budget = RequestBudget(max_requests=10, max_credits=1, reserve=0)
        client = MagicMock()
        with patch.object(ingestion, "ACTIVE_BUDGET", budget):
            code, _, _ = ingestion.get(client, "/fake", {"markets": "player_points,player_rebounds"})
        self.assertEqual(code, 0)
        client.get.assert_not_called()

    def test_missing_quota_stays_unknown_and_reliable_quota_stops(self):
        budget = RequestBudget(reserve=50)
        self.assertTrue(budget.claim(2))
        budget.observe({}, 2, 200)
        self.assertIsNone(budget.remaining)
        budget.observe({"x-requests-remaining": "50", "x-requests-last": "2"}, 2, 200)
        self.assertFalse(budget.claim(0))
        self.assertEqual(budget.reason, "provider_quota")

    def test_transient_retry_counts_attempts_and_hard_budget_prevents_retry(self):
        for limit, expected in ((1, 1), (3, 2)):
            client = MagicMock()
            client.get.side_effect = [response(503, {}), response(200, {})]
            budget = RequestBudget(max_requests=limit, reserve=0)
            with patch.object(ingestion, "ACTIVE_BUDGET", budget), patch.object(ingestion.time, "sleep"):
                ingestion.get(client, "/fake", {})
            self.assertEqual(client.get.call_count, expected)
            self.assertEqual(budget.requests, expected)

    def test_non_retryable_and_provider_quota_errors_are_not_retried(self):
        for code in (400, 401, 402, 403, 422, 429):
            client = MagicMock()
            client.get.return_value = response(code, {"error_code": "OUT_OF_USAGE_CREDITS"})
            with patch.object(ingestion, "ACTIVE_BUDGET", RequestBudget()), patch.object(ingestion.time, "sleep") as sleep:
                ingestion.get(client, "/fake", {})
            self.assertEqual(client.get.call_count, 1)
            sleep.assert_not_called()

    def test_long_or_ambiguous_retry_after_stops_without_early_retry(self):
        from email.utils import format_datetime
        for retry_after in ("120", format_datetime(datetime.now(timezone.utc) + timedelta(minutes=5)), "unparseable"):
            client = MagicMock()
            client.get.return_value = MagicMock(status_code=429, headers={"Retry-After": retry_after},
                json=lambda: {"error_code": "EXCEEDED_FREQ_LIMIT"})
            budget = RequestBudget(max_requests=10, max_credits=100, reserve=0)
            with patch.object(ingestion, "ACTIVE_BUDGET", budget), patch.object(ingestion.time, "sleep") as sleep:
                self.assertEqual(ingestion.get(client, "/sports", {})[0], 429)
            self.assertEqual(client.get.call_count, 1)
            self.assertTrue(budget.stopped)
            sleep.assert_not_called()

    def test_exhausted_frequency_retry_stops_entire_run_budget(self):
        budget = RequestBudget(max_requests=20, reserve=0)
        client = MagicMock()
        client.get.return_value = response(429, {"error_code": "EXCEEDED_FREQ_LIMIT"})
        with patch.object(ingestion, "ACTIVE_BUDGET", budget), patch.object(ingestion.time, "sleep"):
            self.assertEqual(ingestion.get(client, "/fake", {})[0], 429)
            self.assertEqual(ingestion.get(client, "/next-sport", {})[0], 0)
        self.assertEqual(client.get.call_count, 3)
        self.assertTrue(budget.stopped)
        self.assertEqual(budget.reason, "provider_rate_limit")

    def lock_engine(self, acquired=True):
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        connection = engine.connect.return_value.__enter__.return_value
        connection.execute.return_value.scalar.return_value = acquired
        return engine, connection

    def test_lock_connection_is_pinned_and_released_after_exception(self):
        engine, connection = self.lock_engine()
        with self.assertRaisesRegex(RuntimeError, "body failed"):
            with odds_ingestion_lock(engine) as acquired:
                self.assertTrue(acquired)
                engine.connect.return_value.__exit__.assert_not_called()
                raise RuntimeError("body failed")
        queries = [str(call.args[0]) for call in connection.execute.call_args_list]
        self.assertIn("pg_try_advisory_lock", queries[0])
        self.assertIn("pg_advisory_unlock", queries[1])
        engine.connect.return_value.__exit__.assert_called_once()

    def test_contention_does_not_unlock_other_owner(self):
        engine, connection = self.lock_engine(False)
        with odds_ingestion_lock(engine) as acquired:
            self.assertFalse(acquired)
        self.assertEqual(connection.execute.call_count, 1)

    def test_unlock_failure_invalidates_pooled_connection(self):
        engine, connection = self.lock_engine()
        connection.execute.side_effect = [SimpleNamespace(scalar=lambda: True), RuntimeError("unlock failed")]
        with self.assertRaises(RuntimeError):
            with odds_ingestion_lock(engine):
                pass
        connection.invalidate.assert_called_once()


class RunLifecycleTests(unittest.TestCase):
    def run_main(self, acquired=True, failure=False):
        latest, per_run = [], []
        def run(state):
            if failure:
                raise ValueError("test failure")
            state["status"] = "completed"
        with patch.object(ingestion, "odds_ingestion_lock", return_value=nullcontext(acquired)), \
                patch.object(ingestion, "run_ingestion", side_effect=run) as work, \
                patch.object(ingestion, "write_status", side_effect=lambda value: latest.append(copy.deepcopy(value))), \
                patch.object(ingestion, "atomic_json", side_effect=lambda path, value: per_run.append(copy.deepcopy(value))), \
                patch("builtins.print"):
            result = ingestion.main()
        return result, latest, per_run, work

    def test_started_and_completed_have_one_run_id_and_finish_time(self):
        result, latest, _, _ = self.run_main()
        self.assertEqual([row["status"] for row in latest], ["started", "completed"])
        self.assertEqual(latest[0]["run_id"], latest[1]["run_id"])
        self.assertIn("finished_at", result)

    def test_failure_replaces_previous_started_status(self):
        result, latest, _, _ = self.run_main(failure=True)
        self.assertEqual([row["status"] for row in latest], ["started", "failed"])
        self.assertEqual(result["error_category"], "ValueError")

    def test_lock_contention_writes_own_run_only(self):
        result, latest, per_run, work = self.run_main(acquired=False)
        self.assertEqual(result["status"], "skipped_locked")
        self.assertEqual(latest, [])
        self.assertEqual(per_run[0]["status"], "skipped_locked")
        work.assert_not_called()


if __name__ == "__main__":
    unittest.main()
