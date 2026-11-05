"""Offline invented NBA-shaped matchup tests; never application/provider data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, NBAEvidenceRecord, Player, PlayerGameLog, Prop
from app.services.nba_api_provider import normalize_player_statistics, normalize_team_games
from app.services.nba_matchup_context import build_stored_matchup_context
from app.services.nba_season_summary import build_nba_season_summary
from nba_statistics_fixture import PLAYER_ID, statistics_fixture
import test_event_migration_postgres as pg_fixture

NOW = datetime(2026, 10, 18, 18, tzinfo=timezone.utc)
EASTERN = ZoneInfo("America/New_York")
BOS, ORL, LAL = "1610612738", "1610612753", "1610612747"
EVENT_ID = "5c000000-0000-4000-8000-000000000002"
PROP_ID = "5c000000-0000-4000-8000-000000000003"


def fixture_logs(reference=NOW, competition="Regular Season"):
    payload, crosswalk, season, observed = statistics_fixture(reference)
    if competition == "Playoffs":
        result_set = payload["resultSets"][0]
        game_index = result_set["headers"].index("Game_ID")
        season_index = result_set["headers"].index("SEASON_ID")
        for row in result_set["rowSet"]:
            row[game_index] = "004" + row[game_index][3:]
            row[season_index] = "4" + row[season_index][1:]
    logs = [SimpleNamespace(**row) for row in normalize_player_statistics(payload,
        observed_at=observed, crosswalk=crosswalk, season=season, competition=competition)]
    # This separate invented fixture has one team and opponent; the Phase 5B
    # fixture's trade-shaped rows remain unchanged in that suite.
    for row in logs:
        row.stats["_nba"].update(team_id=BOS, opponent_id=ORL)
    return logs


def team_record(day="2026-10-17", game="0022600999", observed=NOW-timedelta(hours=1)):
    # Exercise actual paired-result normalization rather than invented finality.
    headers = ["GAME_ID", "TEAM_ID", "GAME_DATE", "WL", "PTS", "MATCHUP"]
    payload = {"resultSets": [{"name": "LeagueGameLog", "headers": headers, "rowSet": [
        [game, BOS, day, "W", 110, "BOS vs. ORL"],
        [game, ORL, day, "L", 100, "ORL @ BOS"]]}]}
    game = next(row for row in normalize_team_games(payload, observed_at=observed)["records"] if row["kind"] == "game")
    game["observed_at"] = datetime.fromisoformat(game["observed_at"])
    return SimpleNamespace(**game)


class MatchupTests(unittest.TestCase):
    def setUp(self):
        self.player = SimpleNamespace(id=PLAYER_ID, sport="NBA", team="Los Angeles Lakers")
        self.logs = fixture_logs()
        self.event = SimpleNamespace(id=EVENT_ID, sport_key="basketball_nba", home_team="Boston Celtics",
                                     away_team="Orlando Magic", scheduled_start_at=NOW+timedelta(hours=4))
        self.prop = SimpleNamespace(id=PROP_ID, player_id=PLAYER_ID, event_id=EVENT_ID,
                                    event=self.event, opponent="LAL", game_time=NOW+timedelta(days=99))
        self.rows = [team_record()]
        self.db = Mock()
        self.db.scalars.return_value.all.side_effect = lambda: self.rows

    def context(self, **kwargs):
        return build_stored_matchup_context(self.db, self.player, self.logs,
            prop=kwargs.pop("prop", self.prop), now=kwargs.pop("now", NOW), **kwargs)

    def test_exact_linked_identity_and_event_clock_override_mutable_strings(self):
        result = self.context()
        team = result["team_context"]
        self.assertEqual(team["event_id"], EVENT_ID)
        self.assertEqual(team["prop_id"], PROP_ID)
        self.assertEqual((team["team_id"], team["opponent_id"]), (BOS, ORL))
        self.assertEqual(team["reference_date"], "2026-10-18")
        self.assertEqual(result["opponent_history"]["opponent_name"], "Orlando Magic")

    def test_prior_day_conditional_back_to_back(self):
        team = self.context()["team_context"]
        self.assertEqual(team["last_recorded_game"]["date"], "2026-10-17")
        self.assertEqual(team["last_recorded_game"]["game_id"], "0022600999")
        self.assertEqual(team["calendar_day_gap"], 1)
        self.assertEqual(team["full_intervening_days"], 0)
        self.assertEqual(team["conditional_back_to_back"], "yes")
        self.assertEqual(team["last_recorded_game"]["date_precision"], "eastern_date")

    def test_gap_two_unknown_negative_for_incomplete_schedule(self):
        self.rows = [team_record("2026-10-16")]
        team = self.context()["team_context"]
        self.assertEqual((team["calendar_day_gap"], team["full_intervening_days"]), (2, 1))
        self.assertEqual(team["conditional_back_to_back"], "unknown")

    def test_eastern_reference_date_not_utc_date(self):
        self.event.scheduled_start_at = datetime(2026, 10, 19, 1, tzinfo=timezone.utc)
        self.assertEqual(self.context()["team_context"]["reference_date"], "2026-10-18")
        self.assertEqual(self.context()["team_context"]["calendar_day_gap"], 1)

    def test_missing_team_game_is_not_zero_and_keeps_opponent_history(self):
        self.rows = []
        result = self.context()
        self.assertIsNone(result["team_context"]["calendar_day_gap"])
        self.assertIsNone(result["team_context"]["full_intervening_days"])
        self.assertIsNone(result["team_context"]["last_recorded_game"])
        self.assertEqual(result["opponent_history"]["recorded_appearances"], 12)

    def test_only_completed_supported_observations_before_reference(self):
        self.rows[0].payload["status"] = "unfinished"
        self.assertIsNone(self.context()["team_context"]["last_recorded_game"])
        self.rows = [team_record()]
        self.rows[0].observed_at = NOW+timedelta(days=1)
        self.assertIsNone(self.context()["team_context"]["last_recorded_game"])
        self.rows = [team_record("2026-10-16")]
        self.rows[0].observed_at = datetime(2026, 10, 16, 23, tzinfo=timezone.utc)
        self.assertIsNone(self.context()["team_context"]["last_recorded_game"])

    def test_conflicting_observations_and_team_day_games_fail_closed(self):
        other = deepcopy(self.rows[0])
        other.payload["status"] = "unfinished"
        self.rows.append(other)
        self.assertIsNone(self.context()["team_context"]["last_recorded_game"])
        self.rows = [team_record(), team_record(game="0022600998")]
        self.assertIsNone(self.context()["team_context"]["last_recorded_game"])

    def test_latest_recorded_not_actual_latest_and_duplicate_observations_collapse(self):
        self.rows = [team_record("2026-10-14", "0022600998"), team_record(), team_record()]
        self.assertEqual(self.context()["team_context"]["last_recorded_game"]["date"], "2026-10-17")
        self.assertTrue(any("incomplete" in note for note in self.context()["team_context"]["notes"]))

    def test_windows_select_appearance_slots_before_each_denominator(self):
        history = self.context()["opponent_history"]
        self.assertEqual(history["recorded_appearances"], 12)
        self.assertEqual(history["l5"]["points"], {"average": 4, "valid_samples": 4})
        self.assertEqual(history["l5"]["minutes"], {"average": 32.25, "valid_samples": 4})
        self.assertEqual(history["l5"]["rebounds"], {"average": 1.75, "valid_samples": 4})
        self.assertEqual(history["l5"]["assists"], {"average": 2.8, "valid_samples": 5})
        self.assertEqual(history["l10"]["points"], {"average": 9.56, "valid_samples": 9})
        self.assertEqual(history["l5"]["coverage_start"], "2026-10-11")
        self.assertEqual(history["overall"]["coverage_start"], "2026-10-04")

    def test_exact_opponent_ids_zero_and_small_samples(self):
        for row in self.logs[2:]:
            row.stats["_nba"]["opponent_id"] = LAL
        self.logs[1].stats["points"] = None
        self.logs[1].opponent = "ORL"  # display text has no authority
        history = self.context()["opponent_history"]
        self.assertEqual(history["recorded_appearances"], 2)
        self.assertEqual(history["l5"]["appearances"], 2)
        self.assertEqual(history["l10"]["appearances"], 2)
        self.assertEqual(history["l5"]["points"], {"average": 0, "valid_samples": 1})

    def test_no_opponent_history_is_unavailable_not_zero(self):
        for row in self.logs:
            row.stats["_nba"]["opponent_id"] = LAL
        history = self.context()["opponent_history"]
        self.assertEqual(history["status"], "unavailable")
        self.assertIsNone(history["overall"]["points"]["average"])

    def test_season_competition_source_separation_and_no_espn_fill(self):
        self.logs.append(SimpleNamespace(player_id=PLAYER_ID, sport="NBA", source="espn_nba",
            external_game_id="other", game_date=datetime(2026,10,17,12), stats={"points": 999}))
        self.assertEqual(self.context()["opponent_history"]["recorded_appearances"], 12)
        for arguments in ({"season": "2025-26"}, {"competition": "Playoffs"}):
            result = self.context(**arguments)
            self.assertEqual(result["status"], "available")
            self.assertEqual(result["team_context"]["calendar_day_gap"], 1)
            self.assertEqual(result["opponent_history"]["status"], "unavailable")
            self.assertEqual(result["opponent_history"]["recorded_appearances"], 0)
            self.assertIsNone(result["opponent_history"]["overall"]["points"]["average"])

    def test_current_regular_identity_supports_selected_old_season_history(self):
        historical = fixture_logs(NOW-timedelta(days=365))
        # Old affiliation is intentionally different; it cannot override the
        # recent Event team, while its exact opponent history remains useful.
        for row in historical:
            row.stats["_nba"]["team_id"] = LAL
        self.logs.extend(historical)
        result = self.context(season="2025-26")
        self.assertEqual(result["team_context"]["team_id"], BOS)
        self.assertEqual(result["team_context"]["calendar_day_gap"], 1)
        history = result["opponent_history"]
        self.assertEqual(history["season"], "2025-26")
        self.assertEqual(history["source"], "nba_com_stats")
        self.assertEqual(history["recorded_appearances"], 12)
        self.assertEqual(history["l5"]["points"], {"average": 4, "valid_samples": 4})
        self.assertEqual(history["coverage_end"], "2025-10-15")

    def test_current_regular_identity_supports_selected_playoffs_history_without_team_results(self):
        historical = fixture_logs(datetime(2026, 5, 18, 18, tzinfo=timezone.utc), "Playoffs")
        self.logs.extend(historical)
        self.rows = []
        result = self.context(season="2025-26", competition="Playoffs")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["team_context"]["team_id"], BOS)
        self.assertIsNone(result["team_context"]["calendar_day_gap"])
        history = result["opponent_history"]
        self.assertEqual(history["competition"], "Playoffs")
        self.assertEqual(history["recorded_appearances"], 12)
        self.assertEqual(history["coverage_end"], "2026-05-15")
        self.assertEqual(history["l5"]["points"], {"average": 4, "valid_samples": 4})

    def test_recent_affiliation_conflict_across_competitions_cannot_be_hidden_by_selection(self):
        other = fixture_logs(competition="Playoffs")[0]
        other.stats["_nba"]["team_id"] = LAL
        self.logs.append(other)
        for competition in ("Regular Season", "Playoffs"):
            result = self.context(competition=competition)
            self.assertEqual(result["status"], "unavailable")
            self.assertIn("conflict", result["reason"])
        self.db.scalars.assert_not_called()

    def test_selected_historical_samples_do_not_establish_fresh_identity(self):
        self.logs = fixture_logs(NOW-timedelta(days=365))
        result = self.context(season="2025-26")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("14 days", result["reason"])
        self.db.scalars.assert_not_called()

    def test_other_scope_identity_still_respects_observation_and_appearance_guards(self):
        self.logs = fixture_logs()
        for row in self.logs:
            row.stats["_nba"]["observed_at"] = (NOW+timedelta(hours=1)).isoformat()
        result = self.context(competition="Playoffs")
        self.assertEqual(result["status"], "unavailable")
        for row in self.logs:
            row.stats["_nba"]["observed_at"] = (NOW-timedelta(hours=1)).isoformat()
            row.stats["_nba"]["appearance"] = False
        self.assertEqual(self.context(competition="Playoffs")["status"], "unavailable")

    def test_missing_stale_or_conflicting_team_context(self):
        self.logs = []
        self.assertEqual(self.context()["status"], "unavailable")
        self.logs = fixture_logs()
        self.assertEqual(self.context(now=NOW+timedelta(days=30))["status"], "available")  # selected historical reference remains authoritative
        self.event.scheduled_start_at = NOW+timedelta(days=30)
        self.assertEqual(self.context()["status"], "unavailable")
        self.event.scheduled_start_at = NOW
        self.logs[1].stats["_nba"]["team_id"] = LAL
        self.assertEqual(self.context()["status"], "unavailable")
        self.assertEqual(build_nba_season_summary(self.player, self.logs, now=NOW)["status"], "available")

    def test_future_observation_never_establishes_team(self):
        for row in self.logs:
            row.stats["_nba"]["observed_at"] = (NOW+timedelta(hours=1)).isoformat()
        self.assertEqual(self.context()["status"], "unavailable")

    def test_no_prop_no_link_or_wrong_player_are_unavailable_without_db(self):
        self.assertEqual(self.context(prop=None)["status"], "unavailable")
        self.prop.player_id = "wrong"
        self.assertEqual(self.context()["status"], "unavailable")
        self.prop.player_id = PLAYER_ID
        self.prop.event_id = "wrong"
        self.assertEqual(self.context()["status"], "unavailable")
        self.db.scalars.assert_not_called()

    def test_unsupported_event_team_or_sport_does_not_block_summary(self):
        self.event.home_team = "BOS"
        self.assertEqual(self.context()["status"], "unavailable")
        self.event.home_team = "Boston Celtics"
        self.event.sport_key = "basketball_wnba"
        self.assertEqual(self.context()["status"], "unavailable")
        self.assertEqual(build_nba_season_summary(self.player, self.logs, now=NOW)["recorded_appearances"], 12)


@unittest.skipUnless(pg_fixture.TEST_URL, "Explicit disposable PostgreSQL URL unset")
class MatchupPostgresTests(unittest.TestCase):
    setUpClass = classmethod(pg_fixture.EventMigrationPostgresTests.setUpClass.__func__)
    remove_schema = pg_fixture.EventMigrationPostgresTests.remove_schema
    upgrade = pg_fixture.EventMigrationPostgresTests.upgrade

    def setUp(self):
        pg_fixture.EventMigrationPostgresTests.setUp(self)
        self.upgrade("20261018_04")
        with Session(self.engine) as db, db.begin():
            db.add(Player(id=PLAYER_ID, name="Invented Phase 5C test", sport="NBA", team="mutable", team_abbr="BOS"))
            db.add(Event(id=EVENT_ID, provider="fixture_5c", provider_event_id="invented",
                sport_key="basketball_nba", home_team="Boston Celtics", away_team="Orlando Magic",
                scheduled_start_at=NOW+timedelta(hours=4)))
            db.flush()
            db.add(Prop(id=PROP_ID, player_id=PLAYER_ID, event_id=EVENT_ID, prop_type="points", line=20,
                        sportsbook="Unavailable fixture", is_active=False))
            for row in fixture_logs():
                db.add(PlayerGameLog(**vars(row)))
            row = vars(team_record()).copy()
            row.update(provider="nba_com", sport="NBA", fingerprint="0"*64)
            db.add(NBAEvidenceRecord(**row))

    def test_actual_stored_query_and_api_are_read_only_without_provider_http(self):
        from app.routers.players import router
        app = FastAPI()
        app.include_router(router, prefix="/players")
        def database():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = database
        statements = []
        @event.listens_for(self.engine, "before_cursor_execute")
        def record(_conn, _cursor, statement, *_args):
            statements.append(statement)
        with patch("requests.sessions.Session.request", side_effect=AssertionError("No provider HTTP")), TestClient(app) as client:
            result = client.get(f"/players/{PLAYER_ID}/research?prop_id={PROP_ID}")
            self.assertEqual(result.status_code, 200)
            data = result.json()
            # API evaluation uses wall-clock now; the fixed reference remains
            # historical and metadata remains as-known at that reference.
            context = data["matchup_context"]
            self.assertEqual(context["team_context"]["calendar_day_gap"], 1)
            self.assertEqual(context["opponent_history"]["l5"]["points"]["valid_samples"], 4)
            self.assertEqual(data["selected_prop"]["id"], PROP_ID)
            for suffix in ("&season=2025-26", "&competition=Playoffs"):
                response = client.get(f"/players/{PLAYER_ID}/research?prop_id={PROP_ID}{suffix}")
                self.assertEqual(response.status_code, 200)
                selected = response.json()["matchup_context"]
                self.assertEqual(selected["team_context"]["calendar_day_gap"], 1)
                self.assertEqual(selected["opponent_history"]["status"], "unavailable")
                self.assertEqual(selected["opponent_history"]["recorded_appearances"], 0)
            player_only = client.get(f"/players/{PLAYER_ID}/research").json()
            self.assertIsNone(player_only["selected_prop"])
            self.assertEqual(player_only["matchup_context"]["status"], "unavailable")
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement in statements))
