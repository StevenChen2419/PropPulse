"""Ingest real player game logs for trends and multi-sport workload intelligence.

Run from backend/ with the virtual environment active:
    python scripts/fetch_player_game_logs.py

MLB uses the public MLB Stats API. NBA, WNBA, NFL and NHL use ESPN player game-log
responses. Missing or unavailable data is skipped; this script never creates
mock game history.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

load_dotenv(os.path.join(BACKEND_DIR, ".env"), override=True)
load_dotenv(override=True)

from app.database import Base, SessionLocal, engine
from app.models import Player, PlayerGameLog, Prop
from app.services.game_log_fields import espn_stats, number, provider_season
from app.services.team_directory import load_team_directory, normalize_player_name, TeamDirectory
from app.services.player_matching import candidate_index, roster_candidates, MatchingDiagnostics, MatchResult, known_team

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
ESPN_WNBA_API_BASE = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/wnba"
ESPN_WNBA_ATHLETES_URL = "https://sports.core.api.espn.com/v3/sports/basketball/wnba/athletes"
TIMEOUT = 30

MLB_HITTING_FIELDS = {
    "hits": "hits",
    "runs": "runs",
    "rbis": "rbi",
    "total_bases": "totalBases",
    "home_runs": "homeRuns",
}
MLB_PITCHING_FIELDS = {
    "strikeouts": "strikeOuts",
    "hits_allowed": "hits",
    "earned_runs": "earnedRuns",
}
def normalize_name(name: str) -> str:
    return normalize_player_name(name)


def correct_player_team(player: Player, team_directory: TeamDirectory) -> bool:
    candidates = roster_candidates(team_directory, normalize_player_name(player.name))
    if len(candidates) != 1:
        return False
    team = candidates[0]
    # Partial roster metadata cannot erase a verified team or abbreviation.
    if not known_team(team.get("team")) or not known_team(team.get("team_abbr")):
        return False
    if player.team == team["team"] and player.team_abbr == team["team_abbr"]:
        return False
    player.team = team["team"]
    player.team_abbr = team["team_abbr"]
    return True


def active_research_players(db, sport: str) -> list[Player]:
    return (
        db.query(Player)
        .join(Prop)
        .filter(Player.sport == sport)
        .filter(Prop.is_active == True)
        .filter(Prop.book_offers.any())
        .distinct()
        .all()
    )


def active_prop_types(db, player_id: str) -> set[str]:
    return {
        prop_type
        for (prop_type,) in (
            db.query(Prop.prop_type)
            .filter(Prop.player_id == player_id)
            .filter(Prop.is_active == True)
            .filter(Prop.book_offers.any())
            .distinct()
            .all()
        )
    }


def upsert_game_log(db, player: Player, item: dict) -> bool:
    existing = (
        db.query(PlayerGameLog)
        .filter(PlayerGameLog.player_id == player.id)
        .filter(PlayerGameLog.external_game_id == item["external_game_id"])
        .first()
    )
    if existing:
        existing.game_date = item["game_date"]
        existing.opponent = item.get("opponent")
        existing.is_home = item.get("is_home")
        existing.stats = {**(existing.stats or {}), **item["stats"]}
        existing.source = item["source"]
        existing.updated_at = datetime.now()
        return False

    db.add(PlayerGameLog(player_id=player.id, sport=player.sport, **item))
    return True


def request_json(client: httpx.Client, url: str, **kwargs) -> dict:
    response = client.get(url, timeout=TIMEOUT, **kwargs)
    response.raise_for_status()
    return response.json()


def fetch_mlb_logs(db, season: int) -> dict:
    players = active_research_players(db, "MLB")
    summary = {"players": len(players), "matched": 0, "teams_corrected": 0, "created": 0, "updated": 0, "errors": []}
    if not players:
        return summary
    diagnostics = MatchingDiagnostics("MLB", row_unit="player_requests")
    local_names = candidate_index(db.query(Player).filter(Player.sport == "MLB").all() or players)

    with httpx.Client(headers={"User-Agent": "PropPulse/0.1"}) as client:
        try:
            team_directory = load_team_directory(client, "MLB", season)
        except Exception as exc:
            team_directory = {}
            summary["errors"].append(f"Could not load MLB team directory: {exc}")
        try:
            roster = request_json(
                client,
                f"{MLB_API_BASE}/sports/1/players",
                params={"season": season},
            ).get("people", [])
        except Exception as exc:
            summary["errors"].append(f"Could not load MLB players: {exc}")
            report_history_roster_failure(players, diagnostics, summary)
            return summary

        provider_players = candidate_index(roster, lambda item: item.get("fullName", ""))

        for player in players:
            provider_player = history_match(player, local_names, provider_players, team_directory,
                                           diagnostics, "available" if roster else "empty")
            if not provider_player:
                summary["errors"].append(f"MLB player not matched: {player.name}")
                continue

            summary["matched"] += 1
            if correct_player_team(player, team_directory):
                summary["teams_corrected"] += 1
            prop_types = active_prop_types(db, player.id)
            groups = []
            if prop_types.intersection(MLB_HITTING_FIELDS):
                groups.append(("hitting", MLB_HITTING_FIELDS))
            if prop_types.intersection(MLB_PITCHING_FIELDS):
                groups.append(("pitching", MLB_PITCHING_FIELDS))

            for group, field_map in groups:
                try:
                    payload = request_json(
                        client,
                        f"{MLB_API_BASE}/people/{provider_player['id']}/stats",
                        params={"stats": "gameLog", "group": group, "season": season},
                    )
                except Exception as exc:
                    summary["errors"].append(f"{player.name} ({group}): {exc}")
                    continue

                splits = []
                for stat_group in payload.get("stats", []):
                    splits.extend(stat_group.get("splits", []))

                for split in splits:
                    raw_stats = split.get("stat") or {}
                    stats = {
                        prop_type: observed
                        for prop_type, provider_field in field_map.items()
                        if (observed := number(raw_stats.get(provider_field))) is not None
                    }
                    workload_fields = {"pitches": "numberOfPitches", "games_started": "gamesStarted"} if group == "pitching" else {"plate_appearances": "plateAppearances"}
                    for key, provider_key in workload_fields.items():
                        observed = number(raw_stats.get(provider_key))
                        if observed is not None:
                            stats[key] = observed
                    item = {
                        "external_game_id": str((split.get("game") or {}).get("gamePk", "")),
                        "game_date": datetime.fromisoformat(split["date"]),
                        "opponent": (split.get("opponent") or {}).get("name"),
                        "is_home": split.get("isHome"),
                        "stats": stats,
                        "source": "mlb_stats_api",
                    }
                    if not item["external_game_id"] or not stats:
                        continue
                    if upsert_game_log(db, player, item):
                        summary["created"] += 1
                    else:
                        summary["updated"] += 1

            db.commit()
            print(f"  MLB  {player.name}: complete")

    summary["matching_diagnostics"] = diagnostics.report()
    return summary


def parse_espn_number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_espn_made_attempted(value) -> float:
    return parse_espn_number(str(value or "0").split("-", 1)[0])


ESPN_LEAGUES = {"NBA": "basketball/nba", "WNBA": "basketball/wnba", "NFL": "football/nfl", "NHL": "hockey/nhl"}


def history_match(player, local_names, provider_names, directory, diagnostics, roster_status):
    """Reject display-name collisions before selecting an external athlete ID."""
    name = normalize_name(player.name)
    candidates = provider_names.get(name, [])
    teams = roster_candidates(directory, name)
    local = local_names.get(name, [])
    reason = ("ambiguous_player" if len(local) > 1 else
              "roster_name_collision" if len(candidates) > 1 or len(teams) > 1 else
              "missing_player" if not candidates else "matched")
    match = MatchResult(reason, len(local), len(candidates), roster_status)
    diagnostics.record({"player_name": player.name, "prop_type": "historical_game_logs"}, reason, match=match)
    return candidates[0] if reason == "matched" else None


def report_history_roster_failure(players, diagnostics, summary):
    for player in players:
        diagnostics.record({"player_name": player.name, "prop_type": "historical_game_logs"},
            "roster_unavailable", match=MatchResult("roster_unavailable", None, None, "unavailable"))
    summary["matching_diagnostics"] = diagnostics.report()


def fetch_wnba_logs(db, season: int) -> dict:
    return fetch_espn_logs(db, season, "WNBA")


def fetch_espn_logs(db, season: int, sport: str) -> dict:
    league = ESPN_LEAGUES[sport]
    api_base = f"https://site.web.api.espn.com/apis/common/v3/sports/{league}"
    athletes_url = f"https://sports.core.api.espn.com/v3/sports/{league}/athletes"
    players = active_research_players(db, sport)
    summary = {"players": len(players), "matched": 0, "teams_corrected": 0, "created": 0, "updated": 0, "errors": []}
    if not players:
        return summary
    diagnostics = MatchingDiagnostics(sport, row_unit="player_requests")
    local_names = candidate_index(db.query(Player).filter(Player.sport == sport).all() or players)

    with httpx.Client(headers={"User-Agent": "Mozilla/5.0 PropPulse/0.1"}) as client:
        try:
            team_directory = load_team_directory(client, sport, season)
        except Exception as exc:
            team_directory = {}
            summary["errors"].append(f"Could not load {sport} team directory: {exc}")
        try:
            provider_players = []
            for page in range(1, 21):
                payload = request_json(client, athletes_url,
                                       params={"limit": 1000, "active": "true", "page": page})
                provider_players.extend(payload.get("items", []))
                if page >= payload.get("pageCount", 1):
                    break
        except Exception as exc:
            summary["errors"].append(f"Could not load {sport} players: {exc}")
            report_history_roster_failure(players, diagnostics, summary)
            return summary

        by_name = candidate_index(provider_players, lambda item: item.get("displayName") or item.get("fullName") or "")
        for player in players:
            provider_player = history_match(player, local_names, by_name, team_directory,
                                           diagnostics, "available" if provider_players else "empty")
            if not provider_player:
                summary["errors"].append(f"{sport} player not matched: {player.name}")
                continue
            summary["matched"] += 1
            if correct_player_team(player, team_directory):
                summary["teams_corrected"] += 1

            try:
                payload = request_json(
                    client,
                    f"{api_base}/athletes/{provider_player['id']}/gamelog",
                    params={
                        "region": "us",
                        "lang": "en",
                        "contentorigin": "espn",
                        "season": season,
                    },
                )
            except Exception as exc:
                summary["errors"].append(f"{player.name}: {exc}")
                continue

            provider_position = (provider_player.get("position") or {}).get("abbreviation")
            if sport == "NFL" and not provider_position:
                try:
                    details = request_json(client, f"{api_base}/athletes/{provider_player['id']}")
                    provider_position = ((details.get("athlete") or {}).get("position") or {}).get("abbreviation")
                except Exception as exc:
                    summary["errors"].append(f"{player.name} position unavailable: {exc}")
            if provider_position:
                player.position = provider_position

            names = payload.get("names", [])
            events_by_id = payload.get("events") or {}
            rows = []
            for season_type in payload.get("seasonTypes", []):
                if "preseason" in season_type.get("displayName", "").lower():
                    continue
                for category in season_type.get("categories", []):
                    if "preseason" not in category.get("displayName", "").lower():
                        rows.extend(category.get("events", []))

            for row in rows:
                stats = espn_stats(sport, names, row.get("stats", []))
                if not stats or (sport in {"NBA", "WNBA"} and stats.get("minutes", 0) <= 0):
                    continue
                game_id = str(row.get("eventId", ""))
                event = events_by_id.get(game_id) or {}
                raw_date = event.get("gameDate")
                if not game_id or not raw_date:
                    continue
                item = {
                    "external_game_id": game_id,
                    "game_date": datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None),
                    "opponent": (event.get("opponent") or {}).get("displayName"),
                    "is_home": event.get("atVs") == "vs",
                    "stats": stats,
                    "source": f"espn_{sport.lower()}",
                }
                if upsert_game_log(db, player, item):
                    summary["created"] += 1
                else:
                    summary["updated"] += 1

            db.commit()
            print(f"  {sport} {player.name}: complete")

    summary["matching_diagnostics"] = diagnostics.report()
    return summary


def print_summary(sport: str, summary: dict) -> None:
    print(f"\n{sport}")
    print(f"  Live prop players: {summary['players']}")
    print(f"  Provider matches:  {summary['matched']}")
    print(f"  Teams corrected:   {summary['teams_corrected']}")
    print(f"  Logs created:      {summary['created']}")
    print(f"  Logs updated:      {summary['updated']}")
    for error in summary["errors"]:
        print(f"  WARN: {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch real player game logs for all supported sports")
    parser.add_argument("--season", type=int, default=None,
                        help="Provider season year; by default resolved separately for each league")
    parser.add_argument(
        "--sport",
        choices=("NBA", "WNBA", "MLB", "NFL", "NHL", "all"),
        default="all",
        help="Limit ingestion to one sport",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    summaries = {}
    started_at = datetime.now(timezone.utc).isoformat()
    status_path = os.path.join(BACKEND_DIR, "data", "game_log_ingestion_status.json")
    try:
        print("PropPulse historical game-log refresh")
        for sport in ("MLB", *ESPN_LEAGUES):
            if args.sport not in (sport, "all"):
                continue
            season = args.season or provider_season(sport, datetime.now(timezone.utc))
            try:
                summary = (fetch_mlb_logs(db, season) if sport == "MLB"
                           else fetch_espn_logs(db, season, sport))
            except Exception as exc:
                db.rollback()
                summary = {"players": 0, "matched": 0, "teams_corrected": 0,
                           "created": 0, "updated": 0,
                           "errors": [f"{sport} refresh failed: {type(exc).__name__}"]}
            summary["season"] = season
            summary["refreshed_at"] = datetime.now(timezone.utc).isoformat()
            records = summary["created"] + summary["updated"]
            summary["status"] = ("partial" if records else "failed") if summary["errors"] else (
                "completed" if records else "no_data")
            summaries[sport] = summary
            print_summary(sport, summary)
            outcomes = {item["status"] for item in summaries.values()}
            overall = "partial" if outcomes & {"failed", "partial"} else "completed"
            if outcomes == {"failed"}:
                overall = "failed"
            state = {"started_at": started_at, "refreshed_at": datetime.now(timezone.utc).isoformat(),
                     "status": overall, "sports": summaries}
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path + ".tmp", "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2)
            os.replace(status_path + ".tmp", status_path)
    finally:
        db.close()


if __name__ == "__main__":
    main()
