"""Exact public-policy golden captured exclusively from the pre-3I source.

The pre-3I fixture is retained unchanged. Phase 9 explicitly changes last-known
actionability, exact line identity and adds comparison/provider fields. Only these
reviewed differences are adapted below; observation and other policy fields remain
checked against the original oracle.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace as Item
import unittest

from app.services import offer_service

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
GOLDEN = Path(__file__).parent / "fixtures" / "offer_policy_pre_3i.json"


def cases():
    def offer(identity, book="FanDuel", line=20.5, age=timedelta(minutes=10), **changes):
        return Item(**{"id": identity, "sportsbook": book, "line": line,
                       "over_odds": -110, "under_odds": -115,
                       "provider_observed_at": NOW - age,
                       "ingested_at": NOW - timedelta(minutes=1), **changes})
    base = Item(is_active=True, odds_event_id="provider-real-id", event=None,
                game_time=NOW + timedelta(hours=2), sportsbook="FanDuel", line=20.5,
                book_offers=[offer("primary"), offer("alternate", "DraftKings", over_odds=120),
                             offer("different-line", "BetMGM", 21.5, over_odds=200)])
    result = {}
    def add(name, mutate=lambda value: None, *, selected=("FanDuel", 20.5), now=NOW):
        prop = deepcopy(base)
        mutate(prop)
        result[name] = (prop, selected, now)
    add("ordinary")
    for seconds, label in ((1800, "live"), (21600, "ttl")):
        for micros in (-1, 0, 1):
            age = timedelta(seconds=seconds, microseconds=micros)
            add(f"{label}_{micros:+d}us", lambda p, age=age: setattr(p.book_offers[0], "provider_observed_at", NOW-age))
    for delta in (-1, 0, 1):
        add(f"start_{delta:+d}us", lambda p, delta=delta: setattr(p, "game_time", NOW+timedelta(microseconds=delta)))
        add(f"event_start_{delta:+d}us", lambda p, delta=delta: setattr(p, "event", Item(scheduled_start_at=NOW+timedelta(microseconds=delta))))
    for value, label in ((None, "missing"), (NOW+timedelta(microseconds=1), "future")):
        add("observation_"+label, lambda p, value=value: setattr(p.book_offers[0], "provider_observed_at", value))
    for value, label in ((None, "none"), (False, "bool"), (0, "zero"), (99, "99"), (-99, "minus99"),
                         (float("nan"), "nan"), (float("inf"), "inf"), ("-110", "text"), (100, "100"), (-100, "minus100")):
        add("odds_"+label, lambda p, value=value: setattr(p.book_offers[0], "over_odds", value))
    for value, label in ((None, "none"), ("", "empty"), (" ", "blank"), ("mock-id", "mock"),
                         ("Synthetic-id", "synthetic"), ("DEMO-id", "demo"), (1, "nonstring")):
        add("provider_"+label, lambda p, value=value: setattr(p, "odds_event_id", value))
    add("inactive", lambda p: setattr(p, "is_active", False))
    add("missing_start", lambda p: setattr(p, "game_time", None))
    def corrected_event(prop):
        prop.game_time = NOW - timedelta(days=1)
        prop.event = Item(scheduled_start_at=NOW + timedelta(days=1))
    add("future_event_overrides_started_prop", corrected_event)
    add("missing_offers", lambda p: setattr(p, "book_offers", []))
    add("unsupported_selected_book", selected=("UnknownBook", 20.5))
    add("missing_selected_book", selected=(None, 20.5))
    add("different_selected_line", selected=("FanDuel", 19.5))
    add("invalid_selected_line", selected=("FanDuel", None))
    add("primary_missing_alternative_live", lambda p: setattr(p, "book_offers", p.book_offers[1:]))
    add("primary_expired_alternative_live", lambda p: setattr(p.book_offers[0], "provider_observed_at", NOW-timedelta(hours=7)))
    add("all_expired", lambda p: [setattr(o, "provider_observed_at", NOW-timedelta(hours=7)) for o in p.book_offers])
    add("under_only", lambda p: [setattr(o, "over_odds", None) for o in p.book_offers])
    add("unsupported_offer_book", lambda p: setattr(p.book_offers[0], "sportsbook", "UnknownBook"))
    add("duplicate_offer_first_wins", lambda p: p.book_offers.insert(0, offer("duplicate", over_odds=105)))
    add("casefold_book", lambda p: setattr(p.book_offers[0], "sportsbook", "fAnDuEl"), selected=("fAnDuEl", 20.5))
    add("line_inside_tolerance", selected=("FanDuel", 20.5009))
    add("line_outside_tolerance", selected=("FanDuel", 20.5011))
    add("naive_now", now=NOW.replace(tzinfo=None))
    add("offset_now", now=NOW.astimezone(timezone(timedelta(hours=-4))))
    return result


def capture(policy, case):
    prop, (book, line), now = case
    result = {"selected": {side: policy.offer_availability(prop, book, line, side, now)
                         for side in ("over", "under", "invalid")},
            "eligible_offer_ids": [o.id for o in policy.eligible_offers(prop, now)],
            "freshness": policy.odds_freshness(prop, now),
            "primary_prices": policy.primary_prices(prop, now),
            "primary_status": policy.primary_offer_status(prop, now),
            "best_lines": policy.best_line_fields(prop, now)}
    result['best_lines'].pop('comparison', None)  # Separately tested additive contract.
    for row in result['best_lines']['sportsbook_offers']:
        row.pop('provider_bookmaker_key', None)
        row.pop('provider_title', None)
    return result


def phase9_expected(original, name, golden):
    expected = deepcopy(original)
    def research_only(value):
        if isinstance(value, dict):
            if value.get('availability') == 'last_known':
                value['actionable'] = False
            for child in value.values():
                research_only(child)
        elif isinstance(value, list):
            for child in value:
                research_only(child)
    research_only(expected)
    if name == 'line_inside_tolerance':
        expected['selected'] = deepcopy(golden['cases']['different_selected_line']['selected'])
    fields = expected['best_lines']
    for side in ('over', 'under'):
        offers = [o for o in fields['sportsbook_offers'] if o['line'] == 20.5
                  and o['availability'] == 'available' and o[f'{side}_odds'] is not None]
        best = max(offers, key=lambda o: o[f'{side}_odds'], default=None)
        fields[f'best_{side}'] = dict(sportsbook=best['sportsbook'], line=best['line'], odds=best[f'{side}_odds']) if best else None
    return expected


class OfferPolicyEquivalenceTests(unittest.TestCase):
    def test_exact_preoptimization_public_outputs(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        matrix = cases()
        self.assertEqual(set(matrix), set(golden["cases"]))
        self.assertEqual(golden["excluded_fields"], [])
        for name, case in matrix.items():
            with self.subTest(case=name):
                self.assertEqual(capture(offer_service, case), phase9_expected(golden["cases"][name], name, golden))

    def test_compact_best_line_mode_preserves_all_scoring_fields(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for name, case in cases().items():
            prop, _selection, now = case
            expected = {**phase9_expected(golden["cases"][name], name, golden)["best_lines"], "sportsbook_offers": []}
            with self.subTest(case=name):
                self.assertEqual(offer_service.best_line_fields(prop, now, include_offers=False), expected)

    def test_metadata_only_helpers_choose_identical_original_aggregate(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        for name, (prop, _selection, now) in cases().items():
            expected = golden["cases"][name]["freshness"]
            with self.subTest(case=name):
                self.assertEqual(offer_service.offer_refreshed_at(prop, now), expected["refreshed_at"])
                self.assertEqual(offer_service.offer_observation_age(prop, now), expected["observation_age_seconds"])
