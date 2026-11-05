import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace as Item
from app.services.ranking_service import rank_props


class RankingBatchTests(unittest.TestCase):
    def test_unique_player_fatigue_loaded_once_without_changing_scores_or_order(self):
        db = Mock()
        fatigue = Item(player_id="player-a", fatigue_score=0.7, shap_reasons=[], risk_flags=[])
        db.query.return_value.filter.return_value.all.return_value = [fatigue]
        props = [Item(id=str(n), player_id="player-a" if n%2 == 0 else "player-b",
                      player=Item(sport="NBA"), popularity_count=10, prop_type="points",
                      line=20.5, line_24h_ago=20.5) for n in range(100)]
        with patch("app.services.ranking_service.fatigue_to_dict", side_effect=lambda value: value):
            result = rank_props(props, None, db)
        db.query.assert_called_once()
        self.assertEqual([item["prop"].id for item in result],
                         [str(n) for n in range(0,100,2)]+[str(n) for n in range(1,100,2)])
        self.assertEqual(result[0]["rank_score"], 0.265)
        self.assertEqual(result[-1]["rank_score"], 0.195)
        self.assertIs(result[0]["fatigue"], fatigue)
        self.assertIsNone(result[-1]["fatigue"])

    def test_empty_candidates_do_not_query_fatigue(self):
        db = Mock()
        self.assertEqual(rank_props([], None, db), [])
        db.query.assert_not_called()
