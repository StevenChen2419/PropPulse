import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts.fetch_odds import (fetch_player_props, make_sport_status, apply_updates_for_sport,
                                get, fetch_events, should_replace_all_offers, summarize_source)
from app.services.team_directory import load_team_directory


class LiveIngestionTests(unittest.TestCase):
    def test_all_events_are_requested_and_anytime_td_is_parsed(self):
        metadata = {"id": "event", "sport_key": "americanfootball_nfl",
                    "home_team": "Home", "away_team": "Away",
                    "commence_time": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()}
        events = [dict(metadata) for i in range(12)]
        payload = {"id": "event", "sport_key": "americanfootball_nfl", "bookmakers": [{"key": "fanduel", "title": "FanDuel", "markets": [{"key": "player_anytime_td", "outcomes": [
            {"description": "Test Player", "name": "Yes", "price": 120}]}]}]}
        payload.update(metadata)
        status = make_sport_status("americanfootball_nfl")
        with patch("scripts.fetch_odds.time.sleep"), patch("scripts.fetch_odds.get", return_value=(200, payload, {})) as request:
            rows = fetch_player_props(None, "americanfootball_nfl", events, status)
        self.assertEqual(request.call_count, 12)
        self.assertEqual(rows[0]["line"], 0.5)
        self.assertEqual(rows[0]["over_odds"], 120)
        self.assertIsNone(rows[0]["under_odds"])

    def test_quota_exhaustion_stops_requests_and_prevents_replacement(self):
        status = make_sport_status("baseball_mlb")
        with patch("scripts.fetch_odds.get", return_value=(200, {"bookmakers": []}, {"x-requests-remaining": "0"})) as request:
            fetch_player_props(None, "baseball_mlb", [{"id": "1"}, {"id": "2"}], status)
        self.assertEqual(request.call_count, 1)
        self.assertFalse(should_replace_all_offers([{}], status))

    def test_request_exception_does_not_expose_api_key(self):
        client = MagicMock()
        client.get.side_effect = RuntimeError("https://provider?apiKey=SECRET")
        status, payload, headers = get(client, "/sports", {})
        self.assertEqual(status, 0)
        self.assertNotIn("SECRET", str(payload))

    def test_unmatched_demo_is_inactivated_without_random_line_changes(self):
        player = SimpleNamespace(id="p", name="Test", team="Test", sport="MLB")
        prop = SimpleNamespace(id="1", player=player, player_id="p", odds_event_id=None,
                               game_time=None, is_active=True, line=2.5)
        db = MagicMock()
        db.query.return_value.join.return_value.filter.return_value.all.return_value = [prop]
        db.query.return_value.filter.return_value.all.return_value = [player]
        db.query.return_value.join.return_value.join.return_value.filter.return_value.all.return_value = []
        result = apply_updates_for_sport(db, "baseball_mlb", [], make_sport_status("baseball_mlb"))
        self.assertFalse(prop.is_active)
        self.assertEqual(prop.line, 2.5)
        self.assertEqual(result["mock_updated"], 0)
        self.assertEqual(summarize_source([], 0, 0)[0], "unavailable")

    def test_grouped_nfl_rosters_are_flattened(self):
        client = MagicMock()
        teams = {"sports": [{"leagues": [{"teams": [{"team": {"id": "1", "displayName": "Team", "abbreviation": "TM"}}]}]}]}
        roster = {"athletes": [{"position": "offense", "items": [{"displayName": "Test Player"}]}]}
        client.get.return_value.json.side_effect = [teams, roster]
        with patch("app.services.team_directory.httpx.Client") as factory:
            factory.return_value.__enter__.return_value = client
            directory = load_team_directory(None, "NFL", 2026)
        self.assertEqual(directory["test player"]["team_abbr"], "TM")
        self.assertIn("football/nfl/teams", client.get.call_args_list[0].args[0])

    def test_rate_limit_retries_without_treating_it_as_exhausted_quota(self):
        client = MagicMock()
        limited = MagicMock(status_code=429)
        limited.json.return_value = {"error_code": "EXCEEDED_FREQ_LIMIT"}
        success = MagicMock(status_code=200)
        success.json.return_value = []
        client.get.side_effect = [limited, success]
        with patch("scripts.fetch_odds.time.sleep") as sleep:
            status, payload, headers = get(client, "/sports", {})
        self.assertEqual(status, 200)
        self.assertEqual(client.get.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_schedule_filters_started_and_distant_games_and_orders_upcoming(self):
        now = datetime.now(timezone.utc)
        events = [{"id": str(hours), "commence_time": (now + timedelta(hours=hours)).isoformat()}
                  for hours in (30, -1, 100, 2)]
        with patch("scripts.fetch_odds.get", return_value=(200, events, {})):
            result = fetch_events(None, "baseball_mlb", make_sport_status("baseball_mlb"))
        self.assertEqual([item["id"] for item in result], ["2", "30"])
