"""
Fetch real multi-sport player props from The Odds API and update the props table.

Run from backend/ with venv active:
    python scripts/fetch_odds.py

What this does:
  1. Reads THE_ODDS_API_KEY from .env
  2. Confirms the key works via GET /v4/sports
  3. Checks configured sports are active
  4. Fetches upcoming events for NBA, WNBA, NFL, MLB, and NHL
  5. For each event, tries GET /v4/sports/{sport_key}/events/{id}/odds
     with sport-specific player prop markets
  6. Maps returned player prop outcomes onto EXISTING Player rows by
     normalized name match, and updates matching Prop rows in place
  7. Omitted offers and historical snapshots remain stored; availability
     expires through the shared observation-time policy
  8. Missing live players/props are created minimally. Existing prop IDs are
     preserved, and interactions/saved/slips are untouched.

This script ALWAYS writes a status JSON file so the app can explain whether it
used live odds, cached real snapshots, or unavailable data.
"""

import json
import os
import sys
import time
import math
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from sqlalchemy import null

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

load_dotenv(os.path.join(BACKEND_DIR, ".env"), override=True)
load_dotenv(override=True)

from app.database import Base, SessionLocal, engine
from app.models import Player, Prop, PropBook, PropBookSnapshot
from app.services.game_log_fields import provider_season
from app.services.ingestion_control import odds_ingestion_lock, atomic_json, RequestBudget
from app.services.odds_parser import parse_event, parse_utc
from app.services.bookmaker_identity import resolve_book, BOOKMAKERS
from app.services.offer_service import valid_number, valid_odds, utc
from uuid import uuid4
from types import SimpleNamespace
from app.services.offer_service import offer_availability

ACTIVE_BUDGET = None
from app.services.team_directory import load_team_directory, normalize_player_name, TeamDirectory
from app.services.player_matching import candidate_index, match_odds_player, roster_candidates, MatchingDiagnostics
from app.services.event_persistence import (provider_metadata, upsert_event, resolve_prop,
    associate_prop, EventConflict, event_report, finish_event_report, reject)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_KEY = os.getenv("THE_ODDS_API_KEY", "")
BASE_URL = "https://api.the-odds-api.com/v4"
REGIONS = "us"
TIMEOUT = 20
MIN_REMAINING_CREDITS = int(os.getenv("ODDS_MIN_REMAINING_CREDITS", "50"))
EVENT_FETCH_LIMIT = int(os.getenv("ODDS_EVENT_FETCH_LIMIT", "0"))  # 0 fetches every event

SPORT_CONFIG = {
    "basketball_nba": {
        "label": "NBA",
        "markets": {
            "player_points": "points",
            "player_rebounds": "rebounds",
            "player_assists": "assists",
            "player_threes": "threes",
            "player_blocks": "blocks",
            "player_steals": "steals",
            "player_points_rebounds_assists": "pra",
        },
    },
    "basketball_wnba": {
        "label": "WNBA",
        "markets": {
            "player_points": "points",
            "player_rebounds": "rebounds",
            "player_assists": "assists",
            "player_threes": "threes",
            "player_blocks": "blocks",
            "player_steals": "steals",
            "player_points_rebounds_assists": "pra",
        },
    },
    "americanfootball_nfl": {
        "label": "NFL",
        "markets": {
            "player_pass_yds": "pass_yds",
            "player_pass_tds": "pass_tds",
            "player_pass_completions": "pass_completions",
            "player_pass_attempts": "pass_attempts",
            "player_pass_interceptions": "interceptions",
            "player_rush_yds": "rush_yds",
            "player_rush_attempts": "rush_attempts",
            "player_receptions": "receptions",
            "player_reception_yds": "reception_yds",
            "player_anytime_td": "anytime_td",
        },
    },
    "baseball_mlb": {
        "label": "MLB",
        "markets": {
            "batter_home_runs": "home_runs",
            "batter_hits": "hits",
            "batter_total_bases": "total_bases",
            "batter_rbis": "rbis",
            "batter_runs_scored": "runs",
            "pitcher_strikeouts": "strikeouts",
            "pitcher_hits_allowed": "hits_allowed",
            "pitcher_earned_runs": "earned_runs",
        },
    },
    "icehockey_nhl": {
        "label": "NHL",
        "markets": {
            "player_points": "points",
            "player_goals": "goals",
            "player_assists": "assists",
            "player_shots_on_goal": "shots_on_goal",
            "player_blocked_shots": "blocked_shots",
            "player_power_play_points": "power_play_points",
        },
    },
}

CACHE_TTL = timedelta(hours=6)
STATUS_DIR = os.path.join(BACKEND_DIR, "data")
STATUS_PATH = os.path.join(STATUS_DIR, "odds_ingestion_status.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    return normalize_player_name(name)


def make_sport_status(sport_key: str) -> dict:
    config = SPORT_CONFIG[sport_key]
    return {
        "sport_key": sport_key,
        "event_relationships": event_report(),
        "sport": config["label"],
        "active": False,
        "events_found": 0,
        "markets_requested": list(config["markets"].keys()),
        "market_requests_made": 0,
        "market_requests_succeeded": 0,
        "market_requests_failed": 0,
        "live_props_matched": 0,
        "cached_live_props": 0,
        "cached_at": None,
        "cache_age_minutes": None,
        "cache_expires_at": None,
        "cache_ttl_minutes": int(CACHE_TTL.total_seconds() // 60),
        "availability": "unavailable",
        "provider_http_status": None,
        "provider_error_code": None,
        "provider_error_message": None,
        "quota_requests_used": None,
        "quota_requests_remaining": None,
        "quota_requests_last": None,
        "players_created": 0,
        "player_teams_corrected": 0,
        "props_created": 0,
        "props_updated": 0,
        "props_updated_live": 0,
        "props_updated_mock": 0,
        "stale_props_inactivated": 0,
        "unmatched_outcomes": 0,
        "sportsbook_offers_saved": 0,
        "sportsbook_offers_preserved": 0,
        "sportsbook_snapshots_saved": 0,
        "stale_observation_offers_skipped": 0,
        "fallback_used": True,
        "source": "unavailable",
        "warnings": [],
        "errors": [],
        "matchups": [],
        "live_prop_outcomes_received": 0,
        "total_props_seen": 0,
    }


def warn(status: dict, message: str) -> None:
    status["warnings"].append(message)
    print(f"    [WARN] {message}")


def error(status: dict, message: str) -> None:
    status["errors"].append(message)
    print(f"    [ERROR] {message}")


def get(client: httpx.Client, path: str, params: dict, *, max_attempts=3) -> tuple[int, object, dict]:
    """GET helper. Returns (status_code, json_or_none, headers)."""
    params = {**params, "apiKey": API_KEY}
    cost = len(params.get("markets", "").split(",")) if params.get("markets") else 0
    if max_attempts not in (1, 2, 3):
        raise ValueError("Invalid provider attempt limit")
    for attempt in range(max_attempts):
        if ACTIVE_BUDGET is not None and not ACTIVE_BUDGET.claim(cost):
            return 0, {"error_code": "RUN_BUDGET_EXHAUSTED"}, {}
        try:
            resp = client.get(f"{BASE_URL}{path}", params=params, timeout=TIMEOUT)
        except Exception as exc:
            # Unknown network results are charged conservatively; never print URLs.
            return 0, {"error": type(exc).__name__ + ": provider request failed"}, {}
        if ACTIVE_BUDGET is not None:
            ACTIVE_BUDGET.observe(resp.headers, cost, resp.status_code)
        try:
            data = resp.json()
        except Exception:
            data = None
        frequency_limit = resp.status_code == 429 and isinstance(data, dict) and data.get("error_code") == "EXCEEDED_FREQ_LIMIT"
        transient = resp.status_code in (502, 503, 504) or frequency_limit
        if not transient or attempt == max_attempts - 1 or (ACTIVE_BUDGET and ACTIVE_BUDGET.stopped):
            if resp.status_code == 429 and ACTIVE_BUDGET is not None:
                ACTIVE_BUDGET.stopped, ACTIVE_BUDGET.reason = True, "provider_rate_limit"
            return resp.status_code, data, resp.headers
        raw_retry = resp.headers.get("Retry-After")
        try:
            retry_after = float(raw_retry) if raw_retry else 0
        except (TypeError, ValueError):
            try:
                retry_after = (parsedate_to_datetime(raw_retry).astimezone(timezone.utc)
                               - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                retry_after = float("inf")  # Unknown requested wait: fail closed.
        delay = max(2 ** (attempt + 1), retry_after)
        if not math.isfinite(delay):
            delay = 31
        # Do not retry if the provider demands a long wait; the next run backs off.
        if delay > 30:
            if ACTIVE_BUDGET is not None:
                ACTIVE_BUDGET.stopped, ACTIVE_BUDGET.reason = True, "provider_retry_after"
            return resp.status_code, data, resp.headers
        time.sleep(delay)


def extract_provider_error(data: object) -> tuple[str | None, str | None]:
    if not isinstance(data, dict):
        return None, None
    code = data.get("error_code") or data.get("code")
    message = data.get("message") or data.get("error")
    return str(code) if code else None, str(message) if message else None


def provider_error_suffix(data: object) -> str:
    code, message = extract_provider_error(data)
    details = ": ".join(part for part in (code, message) if part)
    return f" ({details})" if details else ""


def record_provider_response(status: dict, status_code: int, data: object, headers: dict) -> None:
    status["provider_http_status"] = status_code
    code, message = extract_provider_error(data)
    if status_code == 0 or status_code >= 400:
        status["provider_error_code"] = code
        status["provider_error_message"] = message
    for key in ("used", "remaining", "last"):
        try:
            value = int(headers.get("x-requests-" + key))
            if value >= 0:
                status["quota_requests_" + key] = value
        except (TypeError, ValueError):
            pass


def determine_availability(status: dict) -> str:
    if status.get("live_props_matched", 0) > 0:
        return "live"
    if status.get("cached_live_props", 0) > 0:
        return "last_known"
    if status.get("events_found", 0) == 0 and status.get("provider_http_status") == 200:
        return "no_games"
    return "unavailable"


def should_replace_all_offers(live_props: list[dict], status: dict) -> bool:
    # Event-odds responses provide no completeness/withdrawal guarantee.
    return False


def parse_game_time(value: str | None):
    return parse_utc(value)


def authoritative_team(item: dict, team_directory: TeamDirectory) -> tuple[str, str]:
    candidates = roster_candidates(team_directory, normalize_player_name(item.get("player_name", "")))
    if len(candidates) != 1:
        return "UNK", "UNK"
    team = candidates[0]
    return team["team"], team["team_abbr"]


def same_team(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return normalize_player_name(left) == normalize_player_name(right)


def team_matches_event(team: str, team_abbr: str, item: dict) -> bool:
    del team_abbr
    return any(
        same_team(team, event_team)
        for event_team in (item.get("home_team"), item.get("away_team"))
    )


def infer_matchup(player: Player, item: dict) -> tuple[bool, str | None]:
    home_team = item.get("home_team")
    away_team = item.get("away_team")

    if same_team(player.team, home_team):
        return True, away_team
    if same_team(player.team, away_team):
        return False, home_team
    return True, away_team or home_team


def repair_self_matchups(props: list[Prop]) -> int:
    by_event: dict[str, list[Prop]] = {}
    for prop in props:
        if prop.odds_event_id:
            by_event.setdefault(prop.odds_event_id, []).append(prop)

    repaired = 0
    for event_props in by_event.values():
        for prop in event_props:
            if not same_team(prop.player.team, prop.opponent):
                continue
            alternatives = {
                (other.player.team, other.is_home)
                for other in event_props
                if not same_team(other.player.team, prop.player.team)
                and same_team(other.opponent, prop.player.team)
            }
            if len(alternatives) != 1:
                continue
            opponent, opponent_is_home = alternatives.pop()
            prop.opponent = opponent
            prop.is_home = not opponent_is_home
            repaired += 1
    return repaired


def summarize_source(events: list[dict], live_updated: int, mock_updated: int) -> tuple[str, str]:
    if live_updated > 0 and mock_updated > 0:
        return "mixed", "Some props used live Odds API player prop data; the rest used mock shifts."
    if live_updated > 0:
        return "odds_api_props", "Props were updated from live Odds API player prop data."
    if events:
        return "odds_api_matchups", "Loaded real matchup context; no usable player prop lines are available."
    return "unavailable", "No live sportsbook lines are available."


def aggregate_status(status_by_sport: dict, api_warnings: list[str], api_errors: list[str]) -> dict:
    sports = list(status_by_sport.values())
    events_found = sum(s["events_found"] for s in sports)
    market_requests_made = sum(s["market_requests_made"] for s in sports)
    live_props_matched = sum(s["live_props_matched"] for s in sports)
    cached_live_props = sum(s["cached_live_props"] for s in sports)
    players_created = sum(s["players_created"] for s in sports)
    player_teams_corrected = sum(s["player_teams_corrected"] for s in sports)
    props_created = sum(s["props_created"] for s in sports)
    props_updated = sum(s["props_updated"] for s in sports)
    props_updated_live = sum(s["props_updated_live"] for s in sports)
    props_updated_mock = sum(s["props_updated_mock"] for s in sports)
    stale_props_inactivated = sum(s["stale_props_inactivated"] for s in sports)
    unmatched_outcomes = sum(s["unmatched_outcomes"] for s in sports)
    sportsbook_offers_saved = sum(s["sportsbook_offers_saved"] for s in sports)
    sportsbook_offers_preserved = sum(s["sportsbook_offers_preserved"] for s in sports)
    sportsbook_snapshots_saved = sum(s["sportsbook_snapshots_saved"] for s in sports)
    live_prop_outcomes_received = sum(s["live_prop_outcomes_received"] for s in sports)
    total_props_seen = sum(s["total_props_seen"] for s in sports)
    matchups = [m for s in sports for m in s["matchups"]]
    warnings = api_warnings + [w for s in sports for w in s["warnings"]]
    errors = api_errors + [e for s in sports for e in s["errors"]]
    cached_at = min((s["cached_at"] for s in sports if s["cached_at"]), default=None)
    cache_expires_at = min(
        (s["cache_expires_at"] for s in sports if s["cache_expires_at"]),
        default=None,
    )
    cache_age_minutes = max(
        (s["cache_age_minutes"] for s in sports if s["cache_age_minutes"] is not None),
        default=None,
    )
    availability_values = {s["availability"] for s in sports}
    if "live" in availability_values:
        availability = "live"
    elif "last_known" in availability_values:
        availability = "last_known"
    elif availability_values == {"no_games"}:
        availability = "no_games"
    else:
        availability = "unavailable"
    quota_remaining = min(
        (int(s["quota_requests_remaining"]) for s in sports if s["quota_requests_remaining"] is not None),
        default=None,
    )
    quota_used = max(
        (int(s["quota_requests_used"]) for s in sports if s["quota_requests_used"] is not None),
        default=None,
    )

    if props_updated_live > 0 and props_updated_mock > 0:
        source = "mixed"
        message = "Some props used live Odds API player prop data; the rest used mock shifts."
    elif props_updated_live > 0:
        source = "odds_api_props"
        message = "Props were updated from live Odds API player prop data."
    elif cached_live_props > 0:
        source = "cached_live"
        message = "The latest Odds API refresh failed; showing the most recent sportsbook snapshot."
    elif events_found > 0:
        source = "odds_api_matchups"
        message = "Loaded real matchup context; no usable player prop lines are available."
    else:
        source = "unavailable"
        message = "No live sportsbook lines are available."

    if not API_KEY:
        message = "THE_ODDS_API_KEY is not set. No live sportsbook lines are available."
    elif not any(s["active"] for s in sports) and cached_live_props == 0:
        message = "Odds API key or sport checks failed. No live sportsbook lines are available."

    nba_status = status_by_sport.get("basketball_nba", {})
    wnba_status = status_by_sport.get("basketball_wnba", {})
    return {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "api_key_loaded": bool(API_KEY),
        "basketball_nba_active": bool(nba_status.get("active", False)),
        "basketball_wnba_active": bool(wnba_status.get("active", False)),
        "events_found": events_found,
        "live_games_found": events_found,
        "markets_requested": sorted({m for s in sports for m in s["markets_requested"]}),
        "market_requests_made": market_requests_made,
        "live_props_matched": live_props_matched,
        "cached_live_props": cached_live_props,
        "cached_at": cached_at,
        "cache_age_minutes": cache_age_minutes,
        "cache_expires_at": cache_expires_at,
        "cache_ttl_minutes": int(CACHE_TTL.total_seconds() // 60),
        "availability": availability,
        "quota_requests_used": quota_used,
        "quota_requests_remaining": quota_remaining,
        "players_created": players_created,
        "player_teams_corrected": player_teams_corrected,
        "props_created": props_created,
        "props_updated": props_updated,
        "props_updated_live": props_updated_live,
        "live_props_updated": props_updated_live,
        "props_updated_mock": props_updated_mock,
        "mock_props_updated": props_updated_mock,
        "total_props_updated": props_updated_live + props_updated_mock,
        "stale_props_inactivated": stale_props_inactivated,
        "unmatched_outcomes": unmatched_outcomes,
        "sportsbook_offers_saved": sportsbook_offers_saved,
        "sportsbook_offers_preserved": sportsbook_offers_preserved,
        "sportsbook_snapshots_saved": sportsbook_snapshots_saved,
        "fallback_used": cached_live_props == 0 and (props_updated_mock > 0 or props_updated_live == 0),
        "source": source,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
        "errors": errors,
        "message": message,
        "matchups": matchups,
        "live_prop_outcomes_received": live_prop_outcomes_received,
        "total_props_seen": total_props_seen,
        "sports": status_by_sport,
    }


# ---------------------------------------------------------------------------
# Step 1-2: verify key and sport availability
# ---------------------------------------------------------------------------

def verify_key_and_sports(client: httpx.Client, status_by_sport: dict) -> bool:
    print("\n[1/5] Verifying API key via GET /v4/sports ...")
    if not API_KEY:
        print("      THE_ODDS_API_KEY not set. (key loaded: no)")
        for status in status_by_sport.values():
            warn(status, "THE_ODDS_API_KEY not set.")
        return False

    status_code, data, headers = get(client, "/sports", {})
    for status in status_by_sport.values():
        record_provider_response(status, status_code, data, headers)

    if status_code == 401:
        print("      401 Unauthorized -- key is invalid. (key loaded: yes, valid: no)")
        for status in status_by_sport.values():
            warn(status, "THE_ODDS_API_KEY rejected with 401 Unauthorized.")
        return False
    if status_code != 200 or not isinstance(data, list):
        print(f"      Unexpected response (HTTP {status_code}). (key loaded: yes, valid: unknown)")
        for status in status_by_sport.values():
            warn(status, f"Sports check returned unexpected response: HTTP {status_code}.")
        return False

    print("      key loaded: yes, valid: yes")
    remaining = headers.get("x-requests-remaining", "?")
    used = headers.get("x-requests-used", "?")
    print(f"      Requests used: {used}, remaining: {remaining}")

    available_by_key = {sport.get("key"): sport for sport in data if isinstance(sport, dict)}
    any_active = False
    for sport_key, config in SPORT_CONFIG.items():
        sport_status = status_by_sport[sport_key]
        entry = available_by_key.get(sport_key)
        if entry is None:
            print(f"      {sport_key}: NOT FOUND in sports list")
            warn(sport_status, f"{sport_key} not found in Odds API sports list.")
            continue

        active = bool(entry.get("active", False))
        sport_status["active"] = active
        any_active = any_active or active
        print(f"      {sport_key} ({config['label']}) active: {'yes' if active else 'no'}")
        if not active:
            warn(sport_status, f"{sport_key} is not active in Odds API sports list.")

    return any_active


# ---------------------------------------------------------------------------
# Step 3: fetch upcoming events
# ---------------------------------------------------------------------------

def fetch_events(client: httpx.Client, sport_key: str, sport_status: dict, *, approved_event_ids=None) -> list[dict]:
    label = SPORT_CONFIG[sport_key]["label"]
    print(f"\n[2/5] Fetching upcoming {label} events ...")
    status_code, data, _headers = get(client, f"/sports/{sport_key}/events", {})
    record_provider_response(sport_status, status_code, data, _headers)

    if status_code != 200 or not isinstance(data, list):
        sport_status["event_discovery_failed"] = True
        sport_status["error_category"] = "provider_event_discovery"
        print(f"      Failed to fetch events (HTTP {status_code}). events found: 0")
        warn(
            sport_status,
            f"Failed to fetch {label} events: HTTP {status_code}{provider_error_suffix(data)}.",
        )
        return []

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    horizon = now + timedelta(hours=int(os.getenv("ODDS_EVENT_HORIZON_HOURS", "48")))
    data = sorted(
        (event for event in data if (start := parse_game_time(event.get("commence_time")))
         and now < start and (event.get('id') in approved_event_ids if approved_event_ids is not None else start <= horizon)),
        key=lambda event: event["commence_time"],
    )
    sport_status["events_found"] = len(data)
    print(f"      events found: {len(data)}")
    for ev in data[:10]:
        print(f"        {ev.get('away_team')} @ {ev.get('home_team')} ({ev.get('commence_time')})")
    return data


# ---------------------------------------------------------------------------
# Step 4: fetch player prop markets per event
# ---------------------------------------------------------------------------

def fetch_player_props(
    client: httpx.Client,
    sport_key: str,
    events: list[dict],
    sport_status: dict,
) -> list[dict]:
    """
    For each event, request player prop markets.
    Returns parsed prop dicts with player_name, prop_type, line, odds,
    sportsbook, game_time, and matchup fields.
    """
    config = SPORT_CONFIG[sport_key]
    label = config["label"]
    market_to_prop_type = config["markets"]
    player_prop_markets = ",".join(market_to_prop_type.keys())

    print(f"\n[3/5] Requesting {label} player prop markets per event ...")
    print(f"      markets requested: {player_prop_markets}")

    if not events:
        print("      No events to query. prop markets requested: 0")
        return []

    parsed: list[dict] = []
    requested = 0
    any_market_data = False
    tier_blocked = False

    selected_events = events[:EVENT_FETCH_LIMIT] if EVENT_FETCH_LIMIT > 0 else events
    sport_status["events_skipped"] = len(events) - len(selected_events)
    for ev in selected_events:
        event_id = ev.get("id")
        home_team = ev.get("home_team")
        away_team = ev.get("away_team")
        commence = ev.get("commence_time")

        if ACTIVE_BUDGET is not None and not ACTIVE_BUDGET.can_request(len(market_to_prop_type)):
            sport_status["events_skipped"] += len(selected_events) - requested
            break
        remaining = sport_status.get("quota_requests_remaining")
        if remaining is not None and int(remaining) <= MIN_REMAINING_CREDITS:
            sport_status["events_skipped"] += len(selected_events) - requested
            warn(sport_status, "Stopped player prop requests: provider quota reserve reached.")
            break
        if requested:
            time.sleep(1)
        requested += 1
        sport_status["market_requests_made"] = requested
        status_code, data, _headers = get(
            client,
            f"/sports/{sport_key}/events/{event_id}/odds",
            {"regions": REGIONS, "markets": player_prop_markets, "oddsFormat": "american"},
        )
        record_provider_response(sport_status, status_code, data, _headers)
        sport_status.setdefault("event_coverage", {})[event_id] = {"status": "failed", "http_status": status_code}

        if status_code in (401, 402, 403, 429) or (status_code == 422 and isinstance(data, dict)
                and data.get("error_code") in {"INVALID_MARKET", "INVALID_MARKETS", "UNSUPPORTED_MARKET"}):
            print(f"      HTTP {status_code} on event odds -- provider rejected the request.")
            warn(
                sport_status,
                f"{label} player prop markets unavailable or rejected: "
                f"HTTP {status_code}{provider_error_suffix(data)}.",
            )
            tier_blocked = True
            sport_status["market_requests_failed"] += 1
            break
        if status_code != 200 or not isinstance(data, dict):
            print(f"      HTTP {status_code} for event {away_team} @ {home_team}. Skipping.")
            warn(
                sport_status,
                f"Skipped {label} prop request for {away_team} @ {home_team}: "
                f"HTTP {status_code}{provider_error_suffix(data)}.",
            )
            sport_status["market_requests_failed"] += 1
            continue

        sport_status["market_requests_succeeded"] += 1
        try:
            rows, issues = parse_event(data, ev, sport_key, config, datetime.now(timezone.utc))
        except Exception as exc:
            sport_status["market_requests_failed"] += 1
            sport_status["event_coverage"][event_id] = {"status": "parse_failed", "error_category": type(exc).__name__}
            continue
        sport_status.setdefault("event_coverage", {})[event_id] = {
            "status": "partial" if issues else "observed", "issues": issues, "offers_received": len(rows)}
        if issues:
            sport_status["ambiguous_events"] = sport_status.get("ambiguous_events", 0) + 1
        try:
            metadata = provider_metadata(data, sport_key)
            if metadata != provider_metadata(ev, sport_key):
                raise EventConflict("event_discovery_metadata_conflict")
            sport_status.setdefault("_authoritative_events", []).append(metadata)
        except EventConflict as exc:
            report = sport_status["event_relationships"]
            report["events_parsed"] += 1
            reject(report, str(exc), event_id)
        parsed.extend(rows)
        any_market_data = any_market_data or bool(rows)

    print(f"      prop markets requested: {requested} event(s)")
    if tier_blocked:
        print("      Result: provider rejected player prop requests; see provider error details.")
    elif not any_market_data:
        print("      Result: requests succeeded but returned no bookmaker data "
              "(off-season or no lines posted yet).")
        warn(sport_status, f"{label} player prop market requests returned no bookmaker data.")
    else:
        print(f"      live prop outcomes parsed: {len(parsed)}")

    sport_status["live_prop_outcomes_received"] = len(parsed)
    return parsed


# ---------------------------------------------------------------------------
# Step 5: map live props onto DB rows, inactivating unmatched demo data
# ---------------------------------------------------------------------------

def cache_offer_is_fresh(prop: Prop, offer, seen_at: datetime) -> bool:
    return bool(
        prop.game_time
        and prop.game_time > seen_at
        and offer.provider_observed_at
        and seen_at - CACHE_TTL <= offer.provider_observed_at <= seen_at
    )


def apply_updates_for_sport(
    db,
    sport_key: str,
    live_props: list[dict],
    sport_status: dict,
    team_directory: TeamDirectory | None = None,
    *, scope: dict | None = None, schedule_corrections: dict | None = None,
    allow_player_changes: bool = True,
) -> dict:
    label = SPORT_CONFIG[sport_key]["label"]
    print(f"\n[4/5] Applying {label} updates to props table ...")

    if scope is not None:
        if team_directory:
            raise ValueError("Scoped persistence must not change roster identity")
        if (set(scope) != {"event_id", "prop_type"} or not scope["event_id"]
                or scope["prop_type"] not in SPORT_CONFIG[sport_key]["markets"].values()):
            raise ValueError("Invalid persistence scope")
        if any(item.get("event_id") != scope["event_id"]
               or item.get("prop_type") != scope["prop_type"]
               or item.get("sport_key") != sport_key for item in live_props):
            raise ValueError("Provider rows expanded persistence scope")
    props_query = db.query(Prop).join(Player).filter(Player.sport == label)
    if scope is not None:
        props_query = props_query.filter(Prop.odds_event_id == scope["event_id"],
                                         Prop.prop_type == scope["prop_type"])
    all_props = props_query.all()
    identity_props = (db.query(Prop).join(Player).filter(Player.sport == label).all()
                      if scope is not None else all_props)
    all_players = db.query(Player).filter(Player.sport == label).all()
    name_lookup = candidate_index(all_players)
    diagnostics = MatchingDiagnostics(label, smoke=scope is not None)
    roster_status = sport_status.get("roster_status", "available" if team_directory else "unavailable")
    sport_status["total_props_seen"] = len(all_props)
    seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
    team_directory = team_directory or {}

    # Authoritative metadata persists independently of athlete/market acceptance.
    relationships = sport_status.setdefault("event_relationships", event_report())
    metadata_by_identity, invalid_events = {}, set()
    invalid_reasons = {}
    supplied = sport_status.pop("_authoritative_events", [])
    for item in live_props:
        try:
            supplied.append(provider_metadata({"id": item.get("event_id"),
                "sport_key": item.get("sport_key", sport_key), "home_team": item.get("home_team"),
                "away_team": item.get("away_team"), "commence_time": item.get("game_time")}, sport_key))
        except EventConflict as exc:
            identity = item.get("event_id")
            invalid_events.add(identity)
            invalid_reasons[identity] = str(exc)
    for metadata in supplied:
        identity = metadata["provider_event_id"]
        if metadata["sport_key"] != sport_key or metadata["provider"] != "the_odds_api":
            invalid_events.add(identity)
        if scope is not None and identity != scope["event_id"]:
            raise ValueError("Event metadata expanded persistence scope")
        if identity in metadata_by_identity and metadata_by_identity[identity] != metadata:
            invalid_events.add(identity)
        metadata_by_identity[identity] = metadata
    events = {}
    relationships["events_parsed"] += len(set(metadata_by_identity) | invalid_events)
    for identity in invalid_events - set(metadata_by_identity):
        reject(relationships, invalid_reasons[identity], identity)
    for identity, metadata in metadata_by_identity.items():
        if identity in invalid_events:
            reject(relationships, "conflicting_event_observations", identity)
            continue
        relationships["events_validated"] += 1
        relationships["database_attempts"] += 1
        try:
            authoritative, action = upsert_event(db, metadata,
                expected_start=(schedule_corrections or {}).get(identity))
            events[identity] = authoritative
            relationships["attempted"]["events_" + action] += 1
            if action == "updated":
                relationships["attempted"]["schedule_changes"] += 1
        except EventConflict as exc:
            reject(relationships, str(exc), identity)

    prop_by_id = {prop.id: prop for prop in all_props}
    offers_query = (
        db.query(PropBook)
        .join(Prop)
        .join(Player)
        .filter(Player.sport == label)
    )
    if scope is not None:
        offers_query = offers_query.filter(Prop.odds_event_id == scope["event_id"],
                                           Prop.prop_type == scope["prop_type"])
    existing_offers = offers_query.all()
    preserve_existing_offers = True
    previous_live_prop_ids = {offer.prop_id for offer in existing_offers}
    existing_offers_by_prop = {}
    for offer in existing_offers:
        existing_offers_by_prop.setdefault(offer.prop_id, []).append(offer)

    grouped_live_props: dict[tuple, dict] = {}
    ambiguous_keys = set()
    for item in live_props:
        if (not normalize_name(item.get("player_name", "")) or not item.get("prop_type")
                or not item.get("provider_bookmaker_key") or not item.get("event_id")
                or not parse_game_time(item.get("game_time")) or not valid_number(item.get("line"))
                or not any(valid_odds(item.get(k)) for k in ("over_odds", "under_odds"))):
            sport_status["unmatched_outcomes"] += 1
            diagnostics.record(item, "invalid_offer")
            continue
        if item.get("event_id") not in events:
            sport_status["unmatched_outcomes"] += 1
            diagnostics.record(item, "event_identity_rejected")
            continue
        group_key = (
            normalize_name(item["player_name"]),
            item["prop_type"],
            item.get("event_id"),
            item.get("game_time"),
            item.get("home_team"),
            item.get("away_team"),
        )
        group = grouped_live_props.setdefault(group_key, {"offers": {}})
        book_key = item["provider_bookmaker_key"]
        identity = (group_key, book_key)
        old = group["offers"].get(book_key)
        if identity in ambiguous_keys:
            diagnostics.record(item, "conflicting_offer_identity")
            sport_status["unmatched_outcomes"] += 1
            continue
        if old is not None and old != item:
            ambiguous_keys.add(identity)
            diagnostics.record(item, "conflicting_offer_identity", rows=2)
            sport_status["unmatched_outcomes"] += 1
        elif old is not None:
            diagnostics.record(item, "duplicate_offer_row")
            sport_status["unmatched_outcomes"] += 1
            continue
        group["offers"][book_key] = item
    for group_key, book_key in ambiguous_keys:
        grouped_live_props[group_key]["offers"].pop(book_key, None)
        sport_status["unmatched_outcomes"] += 1

    live_touched_keys: set[tuple] = set()
    live_touched_prop_ids: set[str] = set()
    live_updated_count = 0
    players_created_count = 0
    player_teams_corrected_count = 0
    props_created_count = 0
    unmatched_outcomes_count = sport_status["unmatched_outcomes"]
    sportsbook_offers_saved = 0
    sportsbook_snapshots_saved = 0
    stale_observation_offers_skipped = 0
    unresolved_prop_ids = set()

    for group in grouped_live_props.values():
        offers = list(group["offers"].values())
        if not offers:
            continue
        item = max(
            offers,
            key=lambda offer: (
                max(
                    offer["over_odds"] if offer["over_odds"] is not None else -100000,
                    offer["under_odds"] if offer["under_odds"] is not None else -100000,
                ),
                offer["sportsbook"],
            ),
        )
        norm = normalize_name(item["player_name"])
        matching = match_odds_player(item, name_lookup, team_directory,
                                    roster_status=roster_status, smoke=scope is not None)
        if not matching.matched:
            unmatched_outcomes_count += len(offers)
            diagnostics.record(item, matching.reason, len(offers), matching)
            continue
        player = matching.player
        roster_team = matching.roster["team"] if matching.roster else "UNK"
        roster_abbr = (matching.roster.get("team_abbr") or "UNK") if matching.roster else "UNK"

        if not player:
            if not allow_player_changes:
                raise ValueError("Player creation requires separate identity approval")
            player = Player(
                name=item["player_name"],
                team=roster_team,
                team_abbr=roster_abbr,
                sport=label,
                position=None,
                age=None,
            )
            db.add(player)
            db.flush()
            all_players.append(player)
            name_lookup.setdefault(norm, []).append(player)
            players_created_count += 1
            print(f"      CREATED {label} PLAYER: '{player.name}' | team={roster_abbr}")
        elif roster_team != "UNK" and (
            player.team != roster_team or player.team_abbr != roster_abbr
        ):
            if not allow_player_changes:
                raise ValueError("Player identity changes require separate approval")
            player.team = roster_team
            player.team_abbr = roster_abbr
            player_teams_corrected_count += 1

        authoritative = events[item["event_id"]]
        game_time = authoritative.scheduled_start_at
        is_home, opponent = infer_matchup(player, item)
        event_id = item.get("event_id")
        event_key = (player.id, item["prop_type"], event_id or game_time, opponent)
        if event_key in live_touched_keys:
            diagnostics.record(item, "duplicate_event_group", len(offers), matching)
            unmatched_outcomes_count += len(offers)
            continue

        try:
            match = resolve_prop(identity_props, player.id, item["prop_type"], authoritative)
        except EventConflict as exc:
            unmatched_outcomes_count += len(offers)
            diagnostics.record(item, str(exc), len(offers), matching)
            reject(relationships, str(exc), event_id, link=True)
            unresolved_prop_ids.update(p.id for p in identity_props
                if p.event_id is None and p.player_id == player.id
                and p.prop_type == item["prop_type"]
                and (p.odds_event_id == event_id or p.odds_event_id is None))
            relationships["legacy_props_unresolved"] = len(unresolved_prop_ids)
            continue

        current = existing_offers_by_prop.get(match.id, []) if match else []
        accepted = []
        for offer in offers:
            key = offer["provider_bookmaker_key"]
            try:
                existing = resolve_book(current, key)
            except ValueError:
                unmatched_outcomes_count += 1
                diagnostics.record(offer, "bookmaker_identity_conflict", match=matching)
                continue
            title = existing.sportsbook if existing else BOOKMAKERS.get(key, (offer["sportsbook"],))[0]
            if any(o.sportsbook == title and o is not existing for o in current):
                unmatched_outcomes_count += 1
                diagnostics.record(offer, "bookmaker_label_collision", match=matching)
                continue
            # Delayed or timestamp-less responses must not replace a known observation.
            observed = offer.get("provider_observed_at")
            if existing and existing.provider_observed_at and (observed is None or observed < existing.provider_observed_at):
                stale_observation_offers_skipped += 1
                diagnostics.record(offer, "stale_provider_observation", match=matching)
                continue
            accepted.append((offer, existing, title))
        if not accepted:
            continue
        item = {**accepted[0][0], "sportsbook": accepted[0][2]}

        if match:
            associate_prop(match, authoritative, relationships)
            match.line_24h_ago = match.line
            match.line = float(item["line"])
            match.over_odds = int(item["over_odds"]) if item["over_odds"] is not None else None
            match.under_odds = int(item["under_odds"]) if item["under_odds"] is not None else None
            match.sportsbook = item["sportsbook"]
            match.odds_event_id = event_id
            match.odds_sport_key = sport_key
            match.odds_last_seen_at = seen_at
            match.game_time = game_time
            match.opponent = opponent
            match.is_home = is_home
            match.is_active = True
            live_updated_count += 1
            print(f"      MATCHED {label}: '{item['player_name']}' -> '{player.name}' "
                  f"| {item['prop_type']} | line={item['line']} | book={item['sportsbook']}")
        else:
            try:
                new_prop = Prop(
                    player_id=player.id,
                    prop_type=item["prop_type"],
                    line=float(item["line"]),
                    line_24h_ago=float(item["line"]),
                    over_odds=int(item["over_odds"]) if item["over_odds"] is not None else null(),
                    under_odds=int(item["under_odds"]) if item["under_odds"] is not None else null(),
                    sportsbook=item["sportsbook"],
                    odds_event_id=event_id,
                    odds_sport_key=sport_key,
                    odds_last_seen_at=seen_at,
                    game_time=game_time,
                    opponent=opponent,
                    is_home=is_home,
                    is_active=True,
                    popularity_count=0,
                )
            except Exception:
                unmatched_outcomes_count += len(accepted)
                diagnostics.record(item, "invalid_prop", len(accepted), matching)
                continue
            db.add(new_prop)
            associate_prop(new_prop, authoritative, relationships)
            db.flush()
            all_props.append(new_prop)
            if identity_props is not all_props:
                identity_props.append(new_prop)
            match = new_prop
            props_created_count += 1
            print(f"      CREATED {label} PROP: '{player.name}' "
                  f"| {item['prop_type']} | line={item['line']} | book={item['sportsbook']}")

        for offer, existing, title in accepted:
            diagnostics.record(offer, "matched", match=matching)
            values = dict(line=float(offer["line"]), over_odds=offer["over_odds"], under_odds=offer["under_odds"])
            changed = existing is None or any(getattr(existing, k) != v for k, v in values.items())
            if existing is None:
                existing = PropBook(prop_id=match.id, sportsbook=title)
                db.add(existing)
                existing_offers.append(existing)
                existing_offers_by_prop.setdefault(match.id, []).append(existing)
            for key, value in values.items():
                setattr(existing, key, value)
            existing.provider_bookmaker_key = offer["provider_bookmaker_key"]
            existing.provider_title = offer["sportsbook"]
            existing.provider_observed_at = offer.get("provider_observed_at")
            existing.ingested_at = seen_at
            existing.updated_at = seen_at
            sportsbook_offers_saved += 1
            if changed:
                db.add(PropBookSnapshot(prop_id=match.id, sportsbook=title, **values, captured_at=seen_at))
                sportsbook_snapshots_saved += 1

        live_touched_keys.add(event_key)
        live_touched_prop_ids.add(match.id)

    mock_updated_count = 0
    stale_inactivated_count = 0
    for prop in (all_props if scope is None else []):
        if prop.id in live_touched_prop_ids:
            continue

        was_live = prop.odds_event_id is not None or prop.id in previous_live_prop_ids
        if was_live:
            if prop.id in previous_live_prop_ids:
                prop.is_active = True
                continue
            if prop.is_active:
                stale_inactivated_count += 1
            prop.is_active = False
            continue

        if prop.is_active:
            stale_inactivated_count += 1
        prop.is_active = False

    live_applied_count = live_updated_count + props_created_count
    cached_prop_ids = (
        previous_live_prop_ids - live_touched_prop_ids
        if preserve_existing_offers
        else set()
    )
    # Use the same policy as HTTP responses; persisted run availability must not
    # call old or timestamp-less provider data Live just because a write succeeded.
    prop_by_id = {prop.id: prop for prop in all_props}
    decisions = []
    eligible_ids = set()
    for offer in existing_offers:
        prop = prop_by_id.get(offer.prop_id)
        if prop is None:
            continue
        view = SimpleNamespace(is_active=prop.is_active, game_time=prop.game_time,
                               odds_event_id=prop.odds_event_id, book_offers=[offer])
        for side in ("over", "under"):
            decision = offer_availability(view, offer.sportsbook, offer.line, side, seen_at)
            # Retained observations inform status even when they cannot be acted on.
            if decision["source"] in {"live", "last_known"}:
                decisions.append(decision)
            if decision["actionable"]:
                eligible_ids.add(prop.id)
    cached_prop_ids &= eligible_ids
    cached_offers = [offer for offer in existing_offers if offer.prop_id in cached_prop_ids
                     and cache_offer_is_fresh(prop_by_id[offer.prop_id], offer, seen_at)]
    cached_live_count = len(cached_prop_ids)
    cached_at = min(
        (offer.provider_observed_at for offer in cached_offers if offer.provider_observed_at),
        default=None,
    )
    cache_expirations = [
        offer.provider_observed_at + CACHE_TTL
        for offer in cached_offers
        if offer.provider_observed_at
    ] + [
        prop_by_id[prop_id].game_time
        for prop_id in cached_prop_ids
        if prop_by_id[prop_id].game_time
    ]
    cache_expires_at = min(cache_expirations, default=None)
    sport_status["events_successfully_processed"] = len({p.odds_event_id for p in all_props if p.id in live_touched_prop_ids})
    sport_status["live_props_matched"] = live_applied_count
    sport_status["cached_live_props"] = cached_live_count
    sport_status["cached_at"] = utc(cached_at).isoformat() if cached_at else None
    sport_status["cache_age_minutes"] = (
        max(0, int((seen_at - cached_at).total_seconds() // 60))
        if cached_at else None
    )
    sport_status["cache_expires_at"] = (
        utc(cache_expires_at).isoformat() if cache_expires_at else None
    )
    sport_status["players_created"] = players_created_count
    sport_status["player_teams_corrected"] = player_teams_corrected_count
    sport_status["props_created"] = props_created_count
    sport_status["props_updated"] = live_updated_count
    sport_status["props_updated_live"] = live_applied_count
    sport_status["props_updated_mock"] = mock_updated_count
    sport_status["stale_props_inactivated"] = stale_inactivated_count
    sport_status["unmatched_outcomes"] = unmatched_outcomes_count
    sport_status["sportsbook_offers_saved"] = sportsbook_offers_saved
    sport_status["sportsbook_offers_preserved"] = max(0, len(existing_offers) - sportsbook_offers_saved)
    sport_status["sportsbook_snapshots_saved"] = sportsbook_snapshots_saved
    sport_status["stale_observation_offers_skipped"] = stale_observation_offers_skipped
    sport_status["matching_diagnostics"] = diagnostics.report()
    sport_status["fallback_used"] = cached_live_count == 0 and (
        mock_updated_count > 0 or live_applied_count == 0
    )
    source, message = summarize_source([], live_applied_count, mock_updated_count)
    if cached_live_count:
        source = "cached_live"
        message = "Latest live request failed; preserving the most recent sportsbook snapshot."
    sport_status["source"] = source
    sport_status["message"] = message
    sport_status["availability"] = ("last_known" if any(d["source"] == "last_known" for d in decisions)
                                    else "live" if decisions else "unavailable")
    if not decisions and sport_status.get("events_found") == 0 and sport_status.get("provider_http_status") == 200:
        sport_status["availability"] = "no_games"

    return {
        "total_props": len(all_props),
        "event_relationships": relationships,
        "live_updated": live_updated_count,
        "live_applied": live_applied_count,
        "cached_live": cached_live_count,
        "players_created": players_created_count,
        "player_teams_corrected": player_teams_corrected_count,
        "props_created": props_created_count,
        "mock_updated": mock_updated_count,
        "stale_inactivated": stale_inactivated_count,
        "unmatched_outcomes": unmatched_outcomes_count,
        "sportsbook_offers_saved": sportsbook_offers_saved,
        "sportsbook_snapshots_saved": sportsbook_snapshots_saved,
        "stale_observation_offers_skipped": stale_observation_offers_skipped,
        "matching_diagnostics": sport_status["matching_diagnostics"],
    }


def finalize_sport_status(sport_status: dict, events: list[dict], live_props: list[dict], api_checked: bool) -> None:
    if sport_status["cached_live_props"]:
        sport_status["source"] = "cached_live"
        sport_status["message"] = "Latest live request failed; preserving the most recent sportsbook snapshot."
        sport_status["matchups"] = [
            f"{event.get('away_team', '?')} @ {event.get('home_team', '?')}"
            for event in events
        ]
        return
    live_applied = sport_status["props_updated"] + sport_status["props_created"]
    source, message = summarize_source(events, live_applied, sport_status["props_updated_mock"])
    sport_status["source"] = source
    sport_status["message"] = message
    sport_status["matchups"] = [
        f"{event.get('away_team', '?')} @ {event.get('home_team', '?')}"
        for event in events
    ]
    if not API_KEY:
        sport_status["message"] = "THE_ODDS_API_KEY is not set. No live sportsbook lines are available."
    elif not api_checked or not sport_status["active"]:
        sport_status["message"] = f"Odds API key or {sport_status['sport']} sport check failed. No live sportsbook lines are available."
    elif events and not live_props:
        sport_status["message"] = "Odds API returned matchup context but no usable player prop lines. No synthetic lines were generated."


def write_status(status: dict) -> None:
    atomic_json(STATUS_PATH, status)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def persist_sports(status_by_sport, live_props_by_sport, team_directories, *, allow_player_changes=True, sport_keys=None):
    """One explicit transaction per sport. Report only committed write counts."""
    counters = ("live_props_matched", "players_created", "player_teams_corrected", "props_created",
                "props_updated", "props_updated_live", "sportsbook_offers_saved", "sportsbook_snapshots_saved",
                "events_successfully_processed")
    for sport_key in SPORT_CONFIG:
        if sport_keys is not None and sport_key not in sport_keys:
            continue
        status = status_by_sport[sport_key]
        try:
            with SessionLocal() as db:
                try:
                    apply_updates_for_sport(db, sport_key, live_props_by_sport.get(sport_key, []),
                                            status, team_directories.get(sport_key, {}),
                                            allow_player_changes=allow_player_changes)
                    db.commit()
                    finish_event_report(status["event_relationships"], "committed")
                    status["matching_diagnostics"]["transaction_outcome"] = "committed"
                except Exception:
                    db.rollback()
                    raise
            status["outcome"] = "partial" if (status.get("market_requests_failed") or status.get("ambiguous_events")
                or status.get("events_skipped") or status.get("unmatched_outcomes")
                or status["event_relationships"]["events_rejected"]) else "completed"
            if status.get("event_discovery_failed") or (not status["active"] and status.get("provider_http_status") != 200):
                status["outcome"] = "failed"
        except Exception as exc:
            finish_event_report(status["event_relationships"], "rolled_back")
            if "matching_diagnostics" in status:
                status["matching_diagnostics"]["transaction_outcome"] = "rolled_back"
            for counter in counters:
                status[counter] = 0
            status["outcome"] = "failed"
            status["error_category"] = "database_" + type(exc).__name__
            status["availability"] = "unavailable"
            status["errors"].append("Sport transaction rolled back: " + type(exc).__name__)


def run_ingestion(run):
    """Called only by the lock owner. No application lifespan or implicit DDL."""
    global ACTIVE_BUDGET
    ACTIVE_BUDGET = RequestBudget(int(os.getenv("ODDS_MAX_REQUESTS_PER_RUN", "100")),
                                  int(os.getenv("ODDS_MAX_CREDITS_PER_RUN", "500")), MIN_REMAINING_CREDITS)
    statuses = {key: make_sport_status(key) for key in SPORT_CONFIG}
    run["sports"] = statuses
    events_by_sport, rows_by_sport, directories = {}, {}, {}
    with httpx.Client() as client:
        active = verify_key_and_sports(client, statuses)
        for key in SPORT_CONFIG:
            status = statuses[key]
            try:
                events_by_sport[key] = fetch_events(client, key, status) if active and status["active"] else []
            except Exception as exc:
                events_by_sport[key] = []
                status["market_requests_failed"] += 1
                status["errors"].append("Event parsing failed: " + type(exc).__name__)
        for key in sorted(SPORT_CONFIG, key=lambda k: events_by_sport[k][0].get("commence_time", "9999") if events_by_sport[k] else "9999"):
            status = statuses[key]
            if ACTIVE_BUDGET.stopped:
                status["events_skipped"] = len(events_by_sport[key])
                rows_by_sport[key] = []
                continue
            try:
                rows_by_sport[key] = fetch_player_props(client, key, events_by_sport[key], status) if status["active"] else []
            except Exception as exc:
                status["market_requests_failed"] += 1
                status["errors"].append("Parser failed: " + type(exc).__name__)
                rows_by_sport[key] = []
            if rows_by_sport[key]:
                try:
                    label = SPORT_CONFIG[key]["label"]
                    directories[key] = load_team_directory(client, label, provider_season(label, datetime.now(timezone.utc)))
                    status["roster_status"] = "available" if directories[key] else "empty"
                except Exception as exc:
                    directories[key] = {}
                    status["roster_status"] = "unavailable"
                    status["warnings"].append("Roster unavailable: " + type(exc).__name__)
    persist_sports(statuses, rows_by_sport, directories)
    for key in SPORT_CONFIG:
        statuses[key]["events_attempted"] = statuses[key]["market_requests_made"]
        statuses[key]["events_failed"] = statuses[key]["market_requests_failed"]
        finalize_sport_status(statuses[key], events_by_sport[key], rows_by_sport.get(key, []), bool(API_KEY))
    report = aggregate_status(statuses, [], [])
    outcomes = {s["outcome"] for s in statuses.values()}
    committed = sum(s["sportsbook_offers_saved"] for s in statuses.values())
    if ACTIVE_BUDGET.stopped:
        outcome = "quota_stopped"
    elif outcomes & {"partial", "failed"}:
        outcome = "partial" if committed else "failed"
    else:
        outcome = "completed"
    run.update(report)
    run.update(ACTIVE_BUDGET.report())
    run["status"] = outcome
    return run


def main():
    run_id = os.getenv("PROPPULSE_ODDS_RUN_ID") or str(uuid4())
    # Accept only UUIDs as file names, including scheduler-supplied IDs.
    from uuid import UUID
    run_id = str(UUID(run_id))
    run = {"run_id": run_id, "status": "started", "started_at": datetime.now(timezone.utc).isoformat()}
    run_path = os.path.join(STATUS_DIR, "odds_runs", run_id + ".json")
    owner = False
    try:
        with odds_ingestion_lock(engine) as acquired:
            if not acquired:
                run.update(status="skipped_locked", finished_at=datetime.now(timezone.utc).isoformat())
                # Never overwrite the active owner's latest status.
                atomic_json(run_path, run)
                print("Odds ingestion skipped: another ingestion owns the dataset lock. Run " + run_id)
                return run
            owner = True
            atomic_json(run_path, run)
            write_status(run)
            try:
                run_ingestion(run)
            except Exception as exc:
                run.update(status="failed", error_category=type(exc).__name__)
            finally:
                run["finished_at"] = datetime.now(timezone.utc).isoformat()
                atomic_json(run_path, run)
                write_status(run)
    except Exception as exc:
        run.update(status="failed", error_category="lock_or_status_" + type(exc).__name__,
                   finished_at=datetime.now(timezone.utc).isoformat())
        atomic_json(run_path, run)
        # Without ownership it is unsafe to replace an active process's status.
        if owner:
            write_status(run)
    finally:
        global ACTIVE_BUDGET
        ACTIVE_BUDGET = None
    print("Odds ingestion " + run["status"] + ". Run " + run_id)
    return run


if __name__ == "__main__":
    result = main()
    sys.exit(1 if result["status"] == "failed" else 0)
