import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.database import get_db
from app.routers.rankings import router
from scripts.fetch_player_game_logs import fetch_espn_logs


class RiskIngestionTests(unittest.TestCase):
    def test_verified_provider_rows_reach_storage_for_each_espn_sport(self):
        fixtures = {"NBA": ("minutes", "32", "minutes", 32),
                    "WNBA": ("minutes", "30", "minutes", 30),
                    "NFL": ("passingAttempts", "28", "pass_attempts", 28),
                    "NHL": ("timeOnIcePerGame", "24:30", "time_on_ice", 24.5)}
        for sport, (field, value, expected_key, expected_value) in fixtures.items():
            with self.subTest(sport=sport):
                player = NS(name="Test Player", position=None)
                db = MagicMock()
                payload = {"names": [field], "events": {
                    "real": {"gameDate": "2026-09-01T19:00:00Z", "atVs": "vs"},
                    "pre": {"gameDate": "2026-08-01T19:00:00Z"}},
                    "seasonTypes": [
                        {"displayName": "Regular Season", "categories": [{"displayName": "Regular", "events": [
                            {"eventId": "real", "stats": [value]}, {"eventId": "missing-date", "stats": [value]}]}]},
                        {"displayName": "Preseason", "categories": [{"events": [{"eventId": "pre", "stats": [value]}]}]}]}
                responses = [
                    {"pageCount": 2, "items": []},
                    {"pageCount": 2, "items": [{"id": "123", "displayName": "Test Player", "position": {"abbreviation": "QB"}}]},
                    payload,
                ]
                with patch("scripts.fetch_player_game_logs.active_research_players", return_value=[player]), \
                     patch("scripts.fetch_player_game_logs.load_team_directory", return_value={}), \
                     patch("scripts.fetch_player_game_logs.request_json", side_effect=responses) as request, \
                     patch("scripts.fetch_player_game_logs.upsert_game_log", return_value=True) as upsert:
                    summary = fetch_espn_logs(db, 2026, sport)
                self.assertEqual(summary["created"], 1)
                self.assertEqual(request.call_args_list[1].kwargs["params"]["page"], 2)
                stored = upsert.call_args.args[2]
                self.assertEqual(stored["source"], "espn_" + sport.lower())
                self.assertEqual(stored["stats"][expected_key], expected_value)
                self.assertEqual(stored["external_game_id"], "real")
                self.assertEqual(player.position, "QB")
                db.commit.assert_called_once()

    def test_risk_endpoint_validates_sport_and_delegates(self):
        app = FastAPI()
        app.include_router(router, prefix="/rankings")
        db = MagicMock()
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        result = {"sports": [], "players": [], "generated_at": "2026-09-07T00:00:00Z"}
        with patch("app.services.risk_intelligence_service.build_risk_intelligence", return_value=result) as build:
            self.assertEqual(client.get("/rankings/risk-intelligence?sport=NHL").json(), result)
            build.assert_called_once_with(db, sport="NHL")
            build.reset_mock()
            self.assertEqual(client.get("/rankings/risk-intelligence?sport=invalid").status_code, 422)
            build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
