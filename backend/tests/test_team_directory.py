import unittest
from types import SimpleNamespace

from app.services.team_directory import normalize_player_name
from scripts.fetch_odds import infer_matchup, repair_self_matchups, team_matches_event
from scripts.fetch_player_game_logs import correct_player_team


class TeamDirectoryTests(unittest.TestCase):
    def test_normalizes_accents_punctuation_and_suffixes(self):
        self.assertEqual(normalize_player_name("Jos\u00e9 Ram\u00edrez Jr."), "jose ramirez")

    def test_authoritative_team_updates_player(self):
        player = SimpleNamespace(name="Jane Doe", team="Wrong Team", team_abbr="WRG")
        changed = correct_player_team(
            player,
            {"jane doe": {"team": "Correct Team", "team_abbr": "COR"}},
        )
        self.assertTrue(changed)
        self.assertEqual(player.team, "Correct Team")
        self.assertEqual(player.team_abbr, "COR")

    def test_missing_roster_match_does_not_guess(self):
        player = SimpleNamespace(name="Unknown Player", team="UNK", team_abbr="UNK")
        self.assertFalse(correct_player_team(player, {}))
        self.assertEqual(player.team, "UNK")

    def test_roster_team_must_belong_to_event(self):
        event = {"home_team": "Atlanta Braves", "away_team": "New York Yankees"}
        self.assertTrue(team_matches_event("Atlanta Braves", "ATL", event))
        self.assertFalse(team_matches_event("Minnesota Twins", "MIN", event))

    def test_team_abbreviation_is_not_matched_as_arbitrary_substring(self):
        event = {
            "home_team": "Dallas Wings",
            "away_team": "Golden State Valkyries",
        }
        player = SimpleNamespace(team="Golden State Valkyries", team_abbr="GS")
        self.assertEqual(infer_matchup(player, event), (False, "Dallas Wings"))

    def test_repairs_self_matchup_from_event_opponent(self):
        event_id = "event-1"
        valkyries = SimpleNamespace(team="Golden State Valkyries")
        wings = SimpleNamespace(team="Dallas Wings")
        bad_prop = SimpleNamespace(
            odds_event_id=event_id,
            player=valkyries,
            opponent="Golden State Valkyries",
            is_home=True,
        )
        valid_prop = SimpleNamespace(
            odds_event_id=event_id,
            player=wings,
            opponent="Golden State Valkyries",
            is_home=True,
        )
        self.assertEqual(repair_self_matchups([bad_prop, valid_prop]), 1)
        self.assertEqual(bad_prop.opponent, "Dallas Wings")
        self.assertFalse(bad_prop.is_home)


if __name__ == "__main__":
    unittest.main()
