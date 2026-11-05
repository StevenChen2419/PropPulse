"""Pre-3I Discover oracle for strict samples and cross-season recent windows."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as Item
import unittest
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from fastapi.encoders import jsonable_encoder
import test_ingestion_postgres as fixture
from app.database import Base
from app.models import Event, Player, PlayerGameLog, Prop, PropBook
from app.routers import props as routes
from app.services import discovery_service, trend_service
from app.services.game_log_fields import provider_season

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
GOLDEN = Path(__file__).parent / "fixtures" / "discover_pre_3i.json"
MARKETS = {"NBA":"points", "NFL":"pass_yds", "NHL":"shots_on_goal", "MLB":"hits", "WNBA":"points"}
SPORT_KEYS = {"NBA":"basketball_nba", "NFL":"americanfootball_nfl", "NHL":"icehockey_nhl",
              "MLB":"baseball_mlb", "WNBA":"basketball_wnba"}


class ClockMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenClock(datetime, metaclass=ClockMeta):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


def uid(label):
    return str(uuid5(NAMESPACE_URL, "m3i-discover-equivalence/"+label))


def cases():
    result = {}
    for sport, market in MARKETS.items():
        for label, count, prior, override in (("four",4,6,None), ("five",5,6,None),
                ("five_one_push",5,6,20.5), ("five_one_missing",5,6,"missing"),
                ("no_history",0,0,None), ("prior_only",0,12,None)):
            name = sport+"/"+label
            prop = Item(id=uid(name), player_id=uid("player/"+name), player=Item(sport=sport),
                        prop_type=market, line=20.5, line_24h_ago=20.5, event=None,
                        game_time=NOW+timedelta(days=2))
            logs = []
            for index in range(count+prior):
                current = index < count
                value = override if index == 0 and override is not None else 25 if index % 2 else 18
                logs.append(Item(game_date=NOW-timedelta(days=index+1 if current else 365+index),
                                 stats={} if value == "missing" else {market:value}, sport=sport,
                                 source="mlb_stats_api" if sport == "MLB" else "espn_"+sport.lower(),
                                 external_game_id=name+"/"+str(index), opponent="Home", is_home=False))
            result[name] = (prop, logs)
    return result


def capture(trends, scoring, case):
    prop, logs = case
    history = trends.build_history_research(prop.player.sport, prop.prop_type, prop.line,
        provider_season(prop.player.sport, prop.game_time), logs, before_game=prop.game_time, now=NOW)
    score = scoring.score_discovery_prop(prop, history["trends"],
        {"sportsbook":"FanDuel", "odds":-110, "line":20.5}, 2)
    return {"research":history, "discovery":score}


def frozen_app_clock(stack, extra_module=None):
    for module in list(sys.modules.values()) + ([extra_module] if extra_module is not None else []):
        if (getattr(module, "__name__", "").startswith("app.") or module is extra_module) and getattr(module, "datetime", None) is datetime:
            stack.enter_context(patch.object(module, "datetime", FrozenClock))


class DiscoverSampleEquivalenceTests(unittest.TestCase):
    def test_strict_season_gate_crossseason_recent_denominators_and_missing_history(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(golden["excluded_fields"], [])
        self.assertEqual(set(cases()), set(golden["cases"]))
        for name, case in cases().items():
            with self.subTest(case=name):
                result = capture(trend_service, discovery_service, case)
                self.assertEqual(result, golden["cases"][name])
                if name.endswith("/five"):
                    self.assertIsNotNone(result["discovery"])
                    self.assertEqual(result["research"]["trends"]["l5"]["season_scope"], "current_season")
                    self.assertEqual(result["research"]["trends"]["l10"]["season_scope"], "mixed_seasons")
                else:
                    self.assertIsNone(result["discovery"])

    def test_prepared_history_cache_matches_uncached_exact_lines_all_sports(self):
        with patch.object(trend_service, "datetime", FrozenClock):
            for name, (prop, logs) in cases().items():
                cache = {}
                for line in (20.5, 18, 25, -1, 0, 100, 20.5):
                    prop.line = line
                    with self.subTest(subject=name, line=line):
                        self.assertEqual(trend_service.build_exact_line_trends(prop, logs, history_cache=cache),
                                         trend_service.build_exact_line_trends(prop, logs))

    def test_cache_isolates_player_sport_market_schedule_and_utc_day(self):
        prop, logs = deepcopy(cases()["NBA/five"])
        cache = {}
        with patch.object(trend_service, "datetime", FrozenClock):
            variants = [deepcopy(prop) for _ in range(5)]
            variants[1].player_id = "other-player"
            variants[2].player.sport = "WNBA"
            variants[3].prop_type = "assists"
            variants[4].game_time -= timedelta(days=4)
            for value in variants:
                self.assertEqual(trend_service.build_exact_line_trends(value, logs, history_cache=cache),
                                 trend_service.build_exact_line_trends(value, logs))
            self.assertEqual(len(cache), 5)
        class NextDay(FrozenClock):
            @classmethod
            def now(cls, tz=None):
                value = NOW + timedelta(days=1)
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)
        with patch.object(trend_service, "datetime", NextDay):
            self.assertEqual(trend_service.build_exact_line_trends(prop, logs, history_cache=cache),
                             trend_service.build_exact_line_trends(prop, logs))
        self.assertEqual(len(cache), 6)

    def test_same_day_future_and_invalid_dates_bypass_prepared_cache(self):
        prop, original = deepcopy(cases()["NBA/five"])
        for date in (NOW-timedelta(hours=1), NOW+timedelta(hours=1), None):
            logs = deepcopy(original)
            logs[0].game_date = date
            logs[0].stats["completed"] = True
            cache = {}
            with self.subTest(date=date), patch.object(trend_service, "datetime", FrozenClock):
                self.assertEqual(trend_service.build_exact_line_trends(prop, logs, history_cache=cache),
                                 trend_service.build_exact_line_trends(prop, logs))
                self.assertEqual(cache, {})

    def test_cache_eviction_recomputes_without_capping_candidates_or_rank(self):
        source, logs = cases()["NBA/five"]
        candidates = []
        for index in range(300):
            prop = deepcopy(source)
            prop.id, prop.player_id = str(index), "player-"+str(index)
            prop.line = 8.5 + index / 100
            candidates.append(prop)
        # Revisit the first exact subject after both FIFO budgets evicted it.
        duplicate = deepcopy(candidates[0])
        duplicate.id = "revisited-first"
        candidates.append(duplicate)
        by_player = {prop.player_id: logs for prop in candidates}
        class Query:
            def query(self, *_args): return self
            def join(self, *_args): return self
            def options(self, *_args): return self
            def filter(self, *_args): return self
            def all(self): return candidates
        sizes, calls, price_calls, score_calls = [], [], [], []
        original_builder = routes.build_exact_line_trends
        def measured(prop, history, *, history_cache):
            sizes.append(len(history_cache))
            calls.append(prop.id)
            return original_builder(prop, history, history_cache=history_cache)
        def serialize(prop, _history, **_kwargs):
            return {"id": prop.id, "sportsbook_count":2,
                    "trends":trend_service.build_exact_line_trends(prop, logs)}
        line_fields = {"best_over":{"sportsbook":"FanDuel", "odds":-110, "line":20.5}, "sportsbook_count":2}
        def price(prop, **_kwargs):
            price_calls.append(prop.id)
            return line_fields
        def score_spy(prop, *args):
            score_calls.append(prop.id)
            return discovery_service.score_discovery_prop(prop, *args)
        expected = []
        with ExitStack() as stack:
            frozen_app_clock(stack)
            for prop in candidates:
                trends = trend_service.build_exact_line_trends(prop, logs)
                score = discovery_service.score_discovery_prop(prop, trends, line_fields["best_over"], 2)
                expected.append(((-score["score"], -trends["l10"]["decisions"], -2), prop.id))
            expected.sort(key=lambda value:value[0])
            stack.enter_context(patch.object(routes, "read_prop_inventory", return_value=candidates))
            stack.enter_context(patch.object(routes, "eligible_offers", return_value=[True]))
            stack.enter_context(patch.object(routes, "load_game_logs", return_value=by_player))
            stack.enter_context(patch.object(routes, "best_line_fields", side_effect=price))
            stack.enter_context(patch.object(routes, "score_discovery_prop", side_effect=score_spy))
            stack.enter_context(patch.object(routes, "latest_refresh", return_value=None))
            stack.enter_context(patch.object(routes, "serialize_prop", side_effect=serialize))
            stack.enter_context(patch.object(routes, "build_exact_line_trends", side_effect=measured))
            response = routes.get_discover(limit=1000, offset=0, sport=None, prop_type=None,
                                           game_key=None, event_id=None, db=Query())
        self.assertEqual(response["total"], 301)
        self.assertEqual([prop["id"] for prop in response["props"]], [identity for _key, identity in expected])
        # Grouped preparation reuses the revisited first subject, while prices
        # and actual scoring still visit all 301 original candidate encounters.
        self.assertEqual(calls, [prop.id for prop in candidates[:-1]])
        self.assertEqual(price_calls, [prop.id for prop in candidates])
        self.assertEqual(score_calls, [prop.id for prop in candidates])
        self.assertLessEqual(max(sizes), 128)

    def test_compact_summaries_preserve_original_scores_for_all_sample_cases_and_lines(self):
        for name, (prop, logs) in cases().items():
            for line in (20.5, 18, 25, -1, 0, 100, 20.5):
                prop.line = line
                trends = capture(trend_service, discovery_service, (prop, logs))["research"]["trends"]
                compact = discovery_service.discovery_history_windows(discovery_service.discovery_history_summary(trends))
                for best, count in ((None, 0), ({"sportsbook":"FanDuel", "odds":-110, "line":line}, 2),
                                    ({"sportsbook":"DraftKings", "odds":150, "line":line}, 5)):
                    with self.subTest(subject=name, line=line, book_count=count):
                        self.assertEqual(discovery_service.score_discovery_prop(prop, compact, best, count),
                                         discovery_service.score_discovery_prop(prop, trends, best, count))

    def test_price_and_sensitive_history_order_with_midnight_fallback(self):
        source, original_logs = cases()["NBA/five"]
        for rollover in (False, True):
            candidates, histories = [], {}
            for index, kind in enumerate(("past", "today", "future", "invalid", "null_start")):
                prop, logs = deepcopy(source), deepcopy(original_logs)
                prop.id, prop.player_id = kind, "player-"+kind
                if kind == "today":
                    logs[0].game_date = NOW-timedelta(hours=1)
                    logs[0].stats["completed"] = True
                elif kind == "future":
                    logs[0].game_date = NOW+timedelta(hours=1)
                elif kind == "invalid":
                    logs[0].game_date = None
                elif kind == "null_start":
                    prop.game_time = None
                candidates.append(prop)
                histories[prop.player_id] = logs
            class Query:
                def query(self, *_args): return self
                def join(self, *_args): return self
                def options(self, *_args): return self
                def filter(self, *_args): return self
            class MovingClock(FrozenClock):
                current = NOW
                @classmethod
                def now(cls, tz=None):
                    return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)
            events = []
            original_builder = routes.build_exact_line_trends
            def history(prop, logs, *, history_cache=None):
                events.append(("prepared_history" if history_cache is not None else "history", prop.id))
                return original_builder(prop, logs, history_cache=history_cache)
            def price(prop, **_kwargs):
                events.append(("price", prop.id))
                if rollover:
                    MovingClock.current = NOW+timedelta(days=1)
                return {"best_over":None, "sportsbook_count":0}
            def score(prop, *args):
                events.append(("score", prop.id))
                return discovery_service.score_discovery_prop(prop, *args)
            with self.subTest(rollover=rollover), ExitStack() as stack:
                frozen_app_clock(stack)
                stack.enter_context(patch.object(routes, "datetime", MovingClock))
                stack.enter_context(patch.object(trend_service, "datetime", MovingClock))
                stack.enter_context(patch.object(routes, "read_prop_inventory", return_value=candidates))
                stack.enter_context(patch.object(routes, "eligible_offers", return_value=[True]))
                stack.enter_context(patch.object(routes, "load_game_logs", return_value=histories))
                stack.enter_context(patch.object(routes, "best_line_fields", side_effect=price))
                stack.enter_context(patch.object(routes, "build_exact_line_trends", side_effect=history))
                stack.enter_context(patch.object(routes, "score_discovery_prop", side_effect=score))
                stack.enter_context(patch.object(routes, "latest_refresh", return_value=None))
                stack.enter_context(patch.object(routes, "serialize_prop", side_effect=lambda prop,*args,**kwargs:{"id":prop.id}))
                routes.get_discover(limit=50, offset=0, sport=None, prop_type=None,
                                    game_key=None, event_id=None, db=Query())
            expected = [("prepared_history", "past")]
            for prop in candidates:
                expected.append(("price", prop.id))
                if rollover or prop.id != "past":
                    expected.append(("history", prop.id))
                expected.append(("score", prop.id))
            self.assertEqual(events, expected)


@unittest.skipUnless(os.environ.get("PROPPULSE_TEST_POSTGRES_URL"), "Explicit isolated PostgreSQL URL unset")
class DiscoverEndpointEquivalencePostgresTests(unittest.TestCase):
    setUpClass = classmethod(fixture.IngestionPostgresTests.setUpClass.__func__)
    remove_schema = fixture.IngestionPostgresTests.remove_schema

    def setUp(self):
        fixture.IngestionPostgresTests.setUp(self)
        Base.metadata.create_all(self.engine)
        with self.Session.begin() as db:
            for name, (subject, logs) in cases().items():
                sport = subject.player.sport
                player = Player(id=subject.player_id, name=name, team="Away", team_abbr="AWY", sport=sport)
                event = Event(id=uid("event/"+name), provider="the_odds_api", sport_key=SPORT_KEYS[sport],
                              provider_event_id=name, home_team="Home", away_team="Away",
                              scheduled_start_at=subject.game_time.replace(tzinfo=None))
                db.add_all([player,event])
                db.flush()
                for duplicate in range(2):
                    prop = Prop(id=uid("prop/"+name+str(duplicate)), player_id=player.id, event_id=event.id,
                                prop_type=subject.prop_type, line=20.5, line_24h_ago=20.5,
                                game_time=event.scheduled_start_at, sportsbook="FanDuel", opponent="Home",
                                is_home=False, odds_event_id=name, odds_sport_key=SPORT_KEYS[sport])
                    db.add(prop)
                    db.flush()
                    db.add_all(PropBook(id=uid("offer/"+name+str(duplicate)+book), prop_id=prop.id,
                        sportsbook=book, line=20.5, over_odds=-110, under_odds=-115,
                        provider_observed_at=(NOW-timedelta(minutes=10)).replace(tzinfo=None),
                        ingested_at=NOW.replace(tzinfo=None)) for book in ("FanDuel","DraftKings"))
                for index, log in enumerate(logs):
                    db.add(PlayerGameLog(id=uid("log/"+name+str(index)), player_id=player.id,
                        sport=sport, source=log.source, external_game_id=log.external_game_id,
                        game_date=log.game_date.replace(tzinfo=None), stats=log.stats,
                        opponent=log.opponent, is_home=log.is_home))

    def endpoint(self, module=routes):
        with ExitStack() as stack:
            frozen_app_clock(stack, module)
            with self.Session() as db:
                result = module.get_discover(limit=50, offset=0, sport=None, prop_type=None,
                                            game_key=None, event_id=None, db=db)
                self.assertFalse(db.new or db.dirty or db.deleted)
                return jsonable_encoder(result)

    def test_exact_preoptimization_response_and_equal_score_order(self):
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))["endpoint"]
        for _ in range(2):
            actual = self.endpoint()
            # The frozen pre-3I oracle predates additive coverage/comparison
            # contract. Preserve its strict comparison for every older field.
            for prop in actual['props']:
                self.assertEqual(prop.pop('statistics_coverage')['completeness'], 'unknown')
                comparison = prop.pop('comparison')
                self.assertEqual(comparison['prop_id'], prop['id'])
                for offer in prop['sportsbook_offers']:
                    self.assertIsNone(offer.pop('provider_bookmaker_key'))
                    self.assertIsNone(offer.pop('provider_title'))
            self.assertEqual(actual, expected)
        self.assertEqual(expected["total"], 10)
        self.assertTrue(all(prop["fatigue"] is None for prop in expected["props"]))
        self.assertEqual(len({prop["discover_score"] for prop in expected["props"]}), 1)
