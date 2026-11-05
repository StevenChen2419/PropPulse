"""Offline comparison tests; no provider, lifespan or application database."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from app.schemas import SportsbookComparisonOut
from app.services.offer_service import best_line_fields, comparison_fields, decimal_price
from app.services.slip_service import slip_selection
from app.routers.players import serialize_line_movement


class SportsbookComparisonTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 21, 18, tzinfo=timezone.utc)
        self.prop = NS(id='prop', player_id='player', event_id='event', event=None,
            prop_type='shots_on_goal', is_active=True, odds_event_id='verified-event',
            sportsbook='FanDuel', line=2.5, game_time=self.now + timedelta(hours=2), book_offers=[])

    def offer(self, book='FanDuel', line=2.5, over=-110, under=120, age=5, **changes):
        row = NS(sportsbook=book, line=line, over_odds=over, under_odds=under,
                 provider_observed_at=self.now - timedelta(minutes=age), ingested_at=self.now,
                 provider_bookmaker_key=book.lower(), provider_title=book)
        for key, value in changes.items():
            setattr(row, key, value)
        self.prop.book_offers.append(row)
        return row

    def group(self, line=2.5, side='over'):
        return next(g for g in comparison_fields(self.prop, self.now)['groups']
                    if (g['line'], g['side']) == (line, side))

    def test_american_prices_and_equivalent_even_money(self):
        for prices in ((105, 120), (-120, -105), (-105, 100)):
            self.prop.book_offers = []
            self.offer(over=prices[0])
            self.offer('DraftKings', over=prices[1])
            self.assertEqual(self.group()['best']['odds'], prices[1])
        self.assertEqual(decimal_price(100), decimal_price(-100))

    def test_ties_are_deterministic_and_do_not_depend_on_input_order(self):
        self.offer(over=-100)
        self.offer('DraftKings', over=100)
        self.assertEqual(self.group()['best']['sportsbook'], 'FanDuel')
        self.prop.book_offers.reverse()
        self.assertEqual(self.group()['best']['sportsbook'], 'FanDuel')
        self.assertEqual(self.group()['advantage_per_100'], 0)

    def test_exact_lines_and_directions_do_not_mix(self):
        self.offer(over=-110, under=110)
        self.offer('DraftKings', line=3.5, over=300, under=-120)
        self.offer('BetMGM', line=2.5001, over=500)
        groups = comparison_fields(self.prop, self.now)['groups']
        self.assertEqual(len(groups), 6)
        fields = best_line_fields(self.prop, self.now)
        self.assertEqual(fields['best_over']['odds'], -110)
        self.assertEqual(fields['best_under']['odds'], 110)
        self.assertEqual(fields['sportsbook_count'], 1)

    def test_identity_and_provider_keys_survive_serialization(self):
        self.offer(provider_bookmaker_key='fanduel', provider_title='FanDuel')
        data = SportsbookComparisonOut(**comparison_fields(self.prop, self.now)).model_dump()
        self.assertEqual((data['prop_id'], data['player_id'], data['event_id'], data['market']),
                         ('prop', 'player', 'event', 'shots_on_goal'))
        self.assertEqual(data['groups'][0]['offers'][0]['provider_bookmaker_key'], 'fanduel')
        other = NS(**{**vars(self.prop), 'id': 'other', 'event_id': 'other-event', 'book_offers': []})
        self.assertEqual(comparison_fields(other, self.now)['groups'], [])

    def test_last_known_is_retained_but_never_beats_live_or_becomes_actionable(self):
        self.offer(over=-110)
        old = self.offer('DraftKings', over=300, age=31)
        group = self.group()
        self.assertEqual(group['best']['sportsbook'], 'FanDuel')
        retained = next(r for r in group['offers'] if r['sportsbook'] == 'DraftKings')
        self.assertEqual(retained['odds'], 300)
        self.assertEqual(retained['availability'], 'last_known')
        self.assertFalse(retained['actionable'])
        item = NS(sportsbook='DraftKings', line=2.5, side='over')
        status = slip_selection(item, self.prop, self.now)
        self.assertFalse(status['actionable'])
        self.assertEqual((item.sportsbook, item.line, item.side), ('DraftKings', 2.5, 'over'))
        old.ingested_at = self.now + timedelta(days=1)
        self.assertEqual(self.group()['best']['sportsbook'], 'FanDuel')

    def test_no_current_best_when_only_stale_or_started(self):
        self.offer(age=31)
        self.assertIsNone(self.group()['best'])
        self.assertIsNone(best_line_fields(self.prop, self.now)['best_over'])
        self.prop.game_time = self.now
        self.assertEqual(self.group()['offers'][0]['availability'], 'game_started')
        self.assertIsNone(self.group()['best'])

    def test_missing_invalid_expired_and_future_observations(self):
        for value in (None, 0, 99, float('nan'), float('inf')):
            self.prop.book_offers = []
            self.offer(over=value)
            self.assertIsNone(self.group()['best'])
            self.assertIsNone(self.group()['offers'][0]['odds'])
        for age in (361, -1):
            self.prop.book_offers = []
            self.offer(age=age)
            self.assertIsNone(self.group()['best'])
        self.prop.book_offers = []
        self.offer(provider_observed_at=None)
        self.assertIsNone(self.group()['offers'][0]['provider_observed_at'])
        self.assertIsNone(self.group()['best'])

    def test_advantage_only_compares_live_prices_at_the_same_line(self):
        self.offer(over=-120)
        self.offer('DraftKings', over=120)
        self.offer('BetMGM', line=3.5, over=500)
        self.assertAlmostEqual(self.group()['advantage_per_100'], 36.6667)
        self.assertIsNone(self.group(3.5)['advantage_per_100'])

    def test_capture_history_is_not_misrepresented_as_observed_movement(self):
        self.offer()
        db = MagicMock()
        self.assertIsNone(serialize_line_movement(db, self.prop))
        db.query.assert_not_called()
        db.commit.assert_not_called()

    def test_compact_scoring_keeps_legacy_fields_and_omits_comparison(self):
        self.offer()
        full = best_line_fields(self.prop, self.now)
        compact = best_line_fields(self.prop, self.now, include_offers=False)
        self.assertEqual(compact, {k: [] if k == 'sportsbook_offers' else v
                                 for k, v in full.items() if k != 'comparison'})


if __name__ == '__main__':
    unittest.main()
