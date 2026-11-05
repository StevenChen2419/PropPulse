"""Candidate matching and complete row accounting; isolated SQLite/mocked providers."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Event, Player, Prop, PropBook, PropBookSnapshot
from app.services.player_matching import candidate_index, match_odds_player, MatchingDiagnostics
from app.services.team_directory import add_roster_candidate, load_mlb_team_directory, load_espn_team_directory
from scripts import fetch_odds as ingestion
from scripts.fetch_player_game_logs import history_match, fetch_espn_logs, correct_player_team
import test_milestone2_ingestion as fixtures


TEAM = {"team": "Home Team", "team_abbr": "HOM", "provider_player_id": "athlete-1"}


class CandidateTests(unittest.TestCase):
    def test_exact_normalized_identity_preserves_existing_match(self):
        player = NS(name="Jos\u00e9 Doe Jr.", team="Home Team")
        row = {**fixtures.parsed()[0], "player_name": "Jose Doe"}
        result = match_odds_player(row, candidate_index([player]), {})
        self.assertTrue(result.matched)
        self.assertIs(result.player, player)

    def test_duplicate_local_names_are_rejected_even_when_one_team_matches(self):
        players = [NS(name="Test Player", team="Home Team"), NS(name="Test Player Jr.", team="Other")]
        result = match_odds_player(fixtures.parsed()[0], candidate_index(players), {})
        self.assertEqual((result.reason, result.candidate_count), ("ambiguous_player", 2))

    def test_scope_unknown_team_and_roster_requirements(self):
        row = fixtures.parsed()[0]
        self.assertEqual(match_odds_player(row, {}, {}, smoke=True).reason, "scope_existing_players_only")
        self.assertEqual(match_odds_player(row, {}, {}).reason, "roster_unavailable")
        self.assertEqual(match_odds_player(row, {}, {}, roster_status="empty").reason, "missing_player")
        unknown = candidate_index([NS(name="Test Player", team="UNK")])
        self.assertEqual(match_odds_player(row, unknown, {}).reason, "unknown_team")
        wrong = candidate_index([NS(name="Test Player", team="Other Team")])
        self.assertEqual(match_odds_player(row, wrong, {}).reason, "team_not_in_event")

    def test_provider_candidates_not_overwritten_or_arbitrarily_disambiguated(self):
        directory = {}
        add_roster_candidate(directory, "Test Player", TEAM, "1")
        add_roster_candidate(directory, "Test Player Jr.", TEAM, "2")
        self.assertEqual(len(directory["test player"]), 2)
        result = match_odds_player(fixtures.parsed()[0], {}, directory)
        self.assertEqual(result.reason, "roster_name_collision")
        player = NS(name="Test Player", team="Old", team_abbr="OLD")
        self.assertFalse(correct_player_team(player, directory))
        self.assertEqual(player.team, "Old")

    def test_identical_provider_identity_does_not_create_false_collision(self):
        directory = {}
        for _ in range(2):
            add_roster_candidate(directory, "Test Player", TEAM, "1")
        self.assertIsInstance(directory["test player"], dict)

    def test_missing_provider_ids_cannot_hide_roster_name_collision(self):
        directory = {}
        for _ in range(2):
            add_roster_candidate(directory, "Test Player", TEAM)
        self.assertEqual(len(directory["test player"]), 2)

    def test_incomplete_history_roster_does_not_erase_known_team_fields(self):
        for roster in ({"team": "UNK", "team_abbr": "UNK"},
                       {"team": "Home Team", "team_abbr": "UNK"},
                       {"team": "Other Team"}, {"team_abbr": "OTH"}):
            with self.subTest(roster=roster):
                player = NS(name="Test Player", team="Home Team", team_abbr="HOM")
                self.assertFalse(correct_player_team(player, {"test player": roster}))
                self.assertEqual((player.team, player.team_abbr), ("Home Team", "HOM"))

    def test_mlb_loader_retains_name_collision(self):
        client = MagicMock()
        client.get.return_value.json.side_effect = [
            {"teams": [{"id": 1, "name": "Home Team", "abbreviation": "HOM"}]},
            {"people": [{"id": athlete, "fullName": "Test Player", "currentTeam": {"id": 1}}
                        for athlete in (1, 2)]}]
        self.assertEqual(len(load_mlb_team_directory(client, 2026)["test player"]), 2)

    def test_espn_loader_retains_name_collision(self):
        client = MagicMock()
        client.get.return_value.json.side_effect = [
            {"sports": [{"leagues": [{"teams": [{"team": {"id": 1, "name": "Home Team"}}]}]}]},
            {"athletes": [{"id": athlete, "displayName": "Test Player"} for athlete in (1, 2)]}]
        with patch("app.services.team_directory.httpx.Client") as factory:
            factory.return_value.__enter__.return_value = client
            self.assertEqual(len(load_espn_team_directory(None, 2026, "NBA")["test player"]), 2)

    def test_history_rejects_both_local_and_provider_collisions(self):
        player = NS(name="Test Player")
        for local, external, reason in [([player, player], [{"id": 1}], "ambiguous_player"),
                                        ([player], [{"id": 1}, {"id": 2}], "roster_name_collision"),
                                        ([player], [], "missing_player")]:
            diagnostics = MatchingDiagnostics("NBA", row_unit="player_requests")
            self.assertIsNone(history_match(player, {"test player": local}, {"test player": external},
                                            {}, diagnostics, "available"))
            self.assertEqual(diagnostics.report()["row_counts"], {reason: 1})

    def test_history_provider_collision_prevents_game_log_request_and_write(self):
        player = NS(name="Test Player", team="Home Team", team_abbr="HOM", position=None)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [player]
        payload = {"pageCount": 1, "items": [{"id": athlete, "displayName": "Test Player"} for athlete in (1, 2)]}
        with patch("scripts.fetch_player_game_logs.active_research_players", return_value=[player]), \
             patch("scripts.fetch_player_game_logs.load_team_directory", return_value={}), \
             patch("scripts.fetch_player_game_logs.request_json", return_value=payload) as request, \
             patch("scripts.fetch_player_game_logs.upsert_game_log") as upsert:
            report = fetch_espn_logs(db, 2027, "NBA")
        request.assert_called_once()
        upsert.assert_not_called()
        db.commit.assert_not_called()
        self.assertEqual(report["matching_diagnostics"]["row_counts"], {"roster_name_collision": 1})

    def test_history_unique_external_identity_preserved(self):
        player, external = NS(name="Test Player"), {"id": "verified-athlete"}
        diagnostics = MatchingDiagnostics("NBA", row_unit="player_requests")
        result = history_match(player, {"test player": [player]}, {"test player": [external]}, {}, diagnostics, "available")
        self.assertIs(result, external)
        self.assertEqual(diagnostics.report()["row_counts"], {"matched": 1})

    def test_skipped_samples_take_priority_over_earlier_matches(self):
        diagnostics = MatchingDiagnostics("NBA", sample_limit=2)
        for i in range(4):
            diagnostics.record({"player_name": f"Matched {i}"}, "matched")
        diagnostics.record({"player_name": "Skipped"}, "missing_player", rows=3)
        report = diagnostics.report()
        self.assertEqual(report["row_counts"], {"matched": 4, "missing_player": 3})
        self.assertEqual(report["samples_truncated"], 3)
        self.assertEqual(len(report["samples"]), 2)
        self.assertTrue(any(sample["reason"] == "missing_player" for sample in report["samples"]))
        self.assertEqual(report["transaction_outcome"], "pending")

    def test_history_unavailable_provider_roster_is_explicit_and_does_not_write(self):
        player = NS(name="Test Player")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [player]
        with patch("scripts.fetch_player_game_logs.active_research_players", return_value=[player]), \
             patch("scripts.fetch_player_game_logs.load_team_directory", return_value={}), \
             patch("scripts.fetch_player_game_logs.request_json", side_effect=RuntimeError("unavailable")), \
             patch("scripts.fetch_player_game_logs.upsert_game_log") as upsert:
            report = fetch_espn_logs(db, 2027, "NBA")
        self.assertEqual(report["matching_diagnostics"]["row_counts"], {"roster_unavailable": 1})
        upsert.assert_not_called()
        db.commit.assert_not_called()


class PersistenceMatchingTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[model.__table__ for model in (Event, Player, Prop, PropBook, PropBookSnapshot)])
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        quiet = patch("builtins.print")
        quiet.start()
        self.addCleanup(quiet.stop)

    def apply(self, rows, directory=None, scope=None):
        status = ingestion.make_sport_status(fixtures.NBA)
        result = ingestion.apply_updates_for_sport(self.db, fixtures.NBA, rows, status, directory, scope=scope)
        self.db.commit()
        return result["matching_diagnostics"]

    def test_missing_unverified_player_not_created(self):
        report = self.apply(fixtures.parsed())
        self.assertEqual(report["row_counts"], {"roster_unavailable": 1})
        self.assertEqual(self.db.query(Player).count(), 0)
        self.assertEqual(self.db.query(Prop).count(), 0)

    def test_unified_refresh_refuses_new_player_and_rolls_back(self):
        status = ingestion.make_sport_status(fixtures.NBA)
        with self.assertRaisesRegex(ValueError, 'separate identity approval'):
            ingestion.apply_updates_for_sport(self.db, fixtures.NBA, fixtures.parsed(), status,
                {"test player": TEAM}, allow_player_changes=False)
        self.db.rollback()
        self.assertEqual(self.db.query(Player).count(), 0)
        self.assertEqual(self.db.query(Prop).count(), 0)
        self.assertEqual(self.db.query(Event).count(), 0)

    def test_unique_verified_roster_creates_player_preserving_repeat_identity(self):
        roster = {"test player": TEAM}
        self.assertEqual(self.apply(fixtures.parsed(), roster)["row_counts"], {"matched": 1})
        player, prop, offer = self.db.query(Player).one(), self.db.query(Prop).one(), self.db.query(PropBook).one()
        ids = (player.id, prop.id, offer.id)
        self.apply(fixtures.parsed(), roster)
        self.assertEqual(ids, (self.db.query(Player).one().id, self.db.query(Prop).one().id, self.db.query(PropBook).one().id))
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)

    def test_group_and_offer_row_units_and_team_mismatch_preserve_existing(self):
        self.apply(fixtures.parsed(), {"test player": TEAM})
        before = self.db.query(PropBook).one().provider_observed_at
        rows = fixtures.parsed() + [{**fixtures.parsed()[0], "provider_bookmaker_key": "draftkings", "sportsbook": "DraftKings"}]
        report = self.apply(rows, {"test player": {"team": "Other", "team_abbr": "OTH"}})
        self.assertEqual(report["row_counts"], {"team_not_in_event": 2})
        self.assertEqual(report["group_counts"], {"team_not_in_event": 1})
        self.assertEqual(report["samples"][0]["affected_rows"], 2)
        self.assertEqual(self.db.query(Player).one().team, "Home Team")
        self.assertEqual(self.db.query(PropBook).one().provider_observed_at, before)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)

    def test_smoke_restriction_reported_without_roster_or_creation(self):
        report = self.apply(fixtures.parsed(), scope={"event_id": "event-1", "prop_type": "points"})
        sample = report["samples"][0]
        self.assertEqual(sample["reason"], "scope_existing_players_only")
        self.assertTrue(sample["smoke_existing_players_only"])
        self.assertEqual(sample["roster_status"], "not_requested_smoke")
        self.assertEqual(self.db.query(Player).count(), 0)

    def test_nonplayer_rejections_have_complete_nonoverlapping_row_counts(self):
        row = fixtures.parsed()[0]
        rows = [row, dict(row), {**row, "line": 99.5}, {**row, "line": 88.5}, {**row, "event_id": None}]
        report = self.apply(rows, {"test player": TEAM})
        self.assertEqual(report["row_counts"], {"duplicate_offer_row": 1, "conflicting_offer_identity": 3, "invalid_offer": 1})
        self.assertEqual(sum(report["row_counts"].values()), len(rows))
        self.assertEqual(self.db.query(PropBook).count(), 0)

    def test_stale_rows_reported_separately_and_history_preserved(self):
        self.apply(fixtures.parsed(), {"test player": TEAM})
        row = {**fixtures.parsed()[0], "provider_observed_at": None, "line": 99.5}
        report = self.apply([row])
        self.assertEqual(report["row_counts"], {"stale_provider_observation": 1})
        self.assertEqual(self.db.query(PropBook).one().line, 20.5)
        self.assertEqual(self.db.query(PropBookSnapshot).count(), 1)

    def test_complete_counts_remain_when_samples_truncated(self):
        report = self.apply([row for i in range(47) for row in fixtures.parsed(name=f"Missing Player {i}")])
        self.assertEqual(report["row_counts"], {"roster_unavailable": 47})
        self.assertEqual(report["group_counts"], {"roster_unavailable": 47})
        self.assertEqual(len(report["samples"]), 40)
        self.assertEqual(report["samples_truncated"], 7)


if __name__ == "__main__":
    unittest.main()
