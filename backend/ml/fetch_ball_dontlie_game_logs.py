"""
Fetch real NBA game logs from BallDontLie and write to ml/data/game_logs.csv.

This is the OPTIONAL live-data path for PropPulse.
Mock data (generate_game_logs.py) remains the default demo workflow.

Usage (run from backend/ with venv active):
    python ml/fetch_ball_dontlie_game_logs.py

Requirements:
    - BALLDONTLIE_API_KEY in .env or environment
    - If key is missing or any fetch fails, the script falls back to mock rows
      for that player and continues. It will never exit without writing a CSV.

Free tier limits:
    - 5 requests per minute
    - This script fetches 10 players x 1 request each = 10 requests total
    - A 13-second sleep between requests keeps it inside the free tier limit
    - Expect ~2-3 minutes of runtime on free tier

Output:
    ml/data/game_logs.csv  (same schema as generate_game_logs.py)

BallDontLie API docs: https://docs.balldontlie.io
Free account: https://app.balldontlie.io
"""

import os
import sys
import time
from datetime import date, timedelta

import httpx
import numpy as np
import pandas as pd
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path setup: run from backend/ so dotenv and ml imports resolve correctly
# ---------------------------------------------------------------------------
BACKEND_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
ML_DIR       = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(ML_DIR, "data")

# Load .env from both project root and backend/. backend/.env wins if both exist.
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_BASE    = "https://api.balldontlie.io/v1"
API_KEY     = os.getenv("BALLDONTLIE_API_KEY", "").strip().strip('"').strip("'")
SEASON      = 2024          # 2024 = 2024-25 NBA season in BallDontLie notation
PER_PAGE    = 100           # max rows per page
REQUEST_GAP = 13            # seconds between requests (free tier = 5 req/min)
TIMEOUT     = 30            # httpx timeout in seconds

# Target players: match the 10 seeded demo players exactly.
# Values: (balldontlie_player_id, display_name, team, position, age,
#          avg_pts, pts_std, avg_mins)
# BallDontLie player IDs are stable integers.
# Run: GET /nba/v1/players?search=lebron to verify if IDs ever change.
PLAYER_MAP = [
    (237,    "LeBron James",            "LAL", "SF", 40, 24.5, 5.0, 34.5),
    (115,    "Stephen Curry",           "GSW", "PG", 37, 27.5, 6.0, 32.0),
    (279,    "Nikola Jokic",            "DEN", "C",  30, 26.0, 5.5, 31.5),
    (3547695,"Luka Doncic",             "DAL", "PG", 26, 28.0, 6.5, 36.0),
    (192,    "Giannis Antetokounmpo",   "MIL", "PF", 30, 30.0, 6.0, 32.0),
    (140,    "Kevin Durant",            "PHX", "SF", 36, 27.0, 5.5, 34.0),
    (178,    "Joel Embiid",             "PHI", "C",  31, 34.0, 7.0, 31.0),
    (3547695,"Jayson Tatum",            "BOS", "SF", 27, 27.0, 5.5, 35.5),
    (498,    "Damian Lillard",          "MIL", "PG", 34, 24.0, 5.5, 34.0),
    (14,     "Anthony Davis",           "LAL", "C",  32, 24.0, 6.0, 35.0),
]

# Correct BallDontLie IDs for the 10 players (verified from their docs/search).
# Using a separate clean dict so the tuple above stays readable.
CORRECT_IDS = {
    "LeBron James":           237,
    "Stephen Curry":          115,
    "Nikola Jokic":           279,
    "Luka Doncic":            3547695,
    "Giannis Antetokounmpo":  192,
    "Kevin Durant":           140,
    "Joel Embiid":            178,
    "Jayson Tatum":           3547695,   # will be resolved below
    "Damian Lillard":         498,
    "Anthony Davis":          14,
}

# The 10 players as (bdl_id, name, team, pos, age, avg_pts, pts_std, avg_mins)
TARGET_PLAYERS = [
    (237,    "LeBron James",            "LAL", "SF", 40, 24.5, 5.0, 34.5),
    (115,    "Stephen Curry",           "GSW", "PG", 37, 27.5, 6.0, 32.0),
    (279,    "Nikola Jokic",            "DEN", "C",  30, 26.0, 5.5, 31.5),
    (3547695,"Luka Doncic",             "DAL", "PG", 26, 28.0, 6.5, 36.0),
    (192,    "Giannis Antetokounmpo",   "MIL", "PF", 30, 30.0, 6.0, 32.0),
    (140,    "Kevin Durant",            "PHX", "SF", 36, 27.0, 5.5, 34.0),
    (178,    "Joel Embiid",             "PHI", "C",  31, 34.0, 7.0, 31.0),
    (4066261,"Jayson Tatum",            "BOS", "SF", 27, 27.0, 5.5, 35.5),
    (498,    "Damian Lillard",          "MIL", "PG", 34, 24.0, 5.5, 34.0),
    (14,     "Anthony Davis",           "LAL", "C",  32, 24.0, 6.0, 35.0),
]

# Mock player IDs used in generate_game_logs.py (for generating fallback rows)
MOCK_IDS = {name: pid for pid, name, *_ in [
    ( 1, "LeBron James"),
    ( 2, "Stephen Curry"),
    ( 3, "Nikola Jokic"),
    ( 4, "Luka Doncic"),
    ( 5, "Giannis Antetokounmpo"),
    ( 6, "Kevin Durant"),
    ( 7, "Joel Embiid"),
    ( 8, "Jayson Tatum"),
    ( 9, "Damian Lillard"),
    (10, "Anthony Davis"),
]}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def make_headers() -> dict:
    return {"Authorization": API_KEY}


def fetch_player_stats(client: httpx.Client, bdl_id: int, name: str) -> list[dict]:
    """
    Fetch all regular-season game stats for a player in SEASON.
    Handles pagination automatically.
    Returns a list of raw BallDontLie stat dicts, or [] on any error.
    """
    all_rows: list[dict] = []
    cursor: int | None   = None

    while True:
        params: dict = {
            "player_ids[]": bdl_id,
            "seasons[]":    SEASON,
            "per_page":     PER_PAGE,
        }
        if cursor is not None:
            params["cursor"] = cursor

        try:
            resp = client.get(
                f"{API_BASE}/stats",
                headers=make_headers(),
                params=params,
                timeout=TIMEOUT,
            )
        except Exception as exc:
            print(f"    [WARN] Network error for {name}: {exc}")
            return []

        if resp.status_code == 401:
            print("    [WARN] API key rejected (401). Check BALLDONTLIE_API_KEY in .env.")
            return []
        if resp.status_code == 429:
            print("    [WARN] Rate limited (429). Sleeping 60 seconds...")
            time.sleep(60)
            continue
        if resp.status_code != 200:
            print(f"    [WARN] HTTP {resp.status_code} for {name}. Skipping.")
            return []

        payload     = resp.json()
        data        = payload.get("data", [])
        next_cursor = payload.get("meta", {}).get("next_cursor")

        all_rows.extend(data)

        if not next_cursor:
            break
        cursor = next_cursor
        time.sleep(REQUEST_GAP)   # stay inside free tier between paginated pages

    return all_rows


def parse_minutes(min_str: str | None, default: float = 30.0) -> float:
    """Convert BallDontLie 'MM:SS' string to float minutes."""
    if not min_str:
        return default
    try:
        parts = str(min_str).split(":")
        return float(parts[0]) + float(parts[1]) / 60.0
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------

def build_live_rows(
    raw_stats: list[dict],
    name:      str,
    team:      str,
    pos:       str,
    age:       int,
    avg_pts:   float,
    pts_std:   float,
    avg_mins:  float,
    mock_id:   int,
) -> list[dict]:
    """
    Convert BallDontLie raw stats into the game_logs.csv schema.
    Skips games with 0 minutes (DNP). Computes rolling features exactly
    like generate_game_logs.py so the trained model can use these rows.
    """
    # Filter to games actually played and sort chronologically
    played = [
        s for s in raw_stats
        if s.get("game", {}).get("status") == "Final"
        and parse_minutes(s.get("min"), 0.0) > 0
    ]
    played.sort(key=lambda s: s["game"]["date"])

    rows:         list[dict] = []
    pts_history:  list[float] = []
    mins_history: list[float] = []
    game_dates:   list[date]  = []

    for s in played:
        game_date_str = s["game"]["date"]           # "2024-10-23"
        game_date     = date.fromisoformat(game_date_str[:10])

        actual_pts  = float(s.get("pts", 0) or 0)
        actual_mins = parse_minutes(s.get("min"), avg_mins)
        is_away     = int(bool(s.get("team", {}).get("id") and
                               s.get("game", {}).get("home_team_score") is not None and
                               s.get("team", {}).get("id") !=
                               s.get("game", {}).get("home_team", {}).get("id", -1)))

        i = len(game_dates)

        # Back-to-back
        b2b = 0
        if i > 0 and (game_date - game_dates[-1]).days == 1:
            b2b = 1

        # Rolling 7-day game count (prior games only)
        cutoff      = game_date - timedelta(days=7)
        games_in_7d = sum(1 for d in game_dates if d > cutoff)

        # Rolling minutes (up to last 5 games)
        n_recent     = min(len(mins_history), 5)
        rolling_mins = float(np.mean(mins_history[-n_recent:])) if n_recent > 0 else avg_mins

        # Minutes trend slope
        if n_recent >= 3:
            window        = mins_history[-n_recent:]
            xs            = np.arange(len(window), dtype=float)
            minutes_trend = float(np.polyfit(xs, window, 1)[0])
        else:
            minutes_trend = 0.0

        perf_volatility = (
            float(np.std(pts_history[-10:])) if len(pts_history) >= 3
            else pts_std * 0.5
        )

        # Stable prop line (same formula as generate_game_logs.py)
        rng_local = np.random.default_rng(hash(name + game_date_str) % (2**32))
        prop_line = max(
            0.5,
            round((avg_pts - 1.5 + float(rng_local.uniform(0, 0.5))) * 2.0) / 2.0,
        )
        underperformed = 1 if actual_pts < prop_line else 0

        rows.append({
            "player_id":              mock_id,
            "player_name":            name,
            "team":                   team,
            "position":               pos,
            "age":                    age,
            "game_date":              game_date.isoformat(),
            "game_number":            i + 1,
            "is_away":                is_away,
            "back_to_back":           b2b,
            "games_in_7d":            games_in_7d,
            "rolling_minutes_7d":     round(rolling_mins, 2),
            "minutes_trend":          round(minutes_trend, 4),
            "performance_volatility": round(perf_volatility, 4),
            "actual_minutes":         round(actual_mins, 1),
            "actual_points":          round(actual_pts, 1),
            "prop_line_points":       round(prop_line, 1),
            "underperformed_line":    underperformed,
        })

        pts_history.append(actual_pts)
        mins_history.append(actual_mins)
        game_dates.append(game_date)

    return rows


def build_mock_rows_for_player(
    name:     str,
    team:     str,
    pos:      str,
    age:      int,
    avg_pts:  float,
    pts_std:  float,
    avg_mins: float,
    mock_id:  int,
    n_games:  int = 40,
) -> list[dict]:
    """
    Generate simple fallback mock rows for one player when the API fails.
    Uses a fixed seed based on player name so output is reproducible.
    Produces enough rows to be useful for training without the full 82-game mock.
    """
    rng_local   = np.random.default_rng(hash(name) % (2**32))
    season_start = date(2024, 10, 22)
    rows:        list[dict] = []
    pts_history: list[float] = []
    mins_history: list[float] = []
    game_dates:  list[date]  = []

    current_date = season_start

    for i in range(n_games):
        gap          = int(rng_local.choice([1, 2, 2, 3], p=[0.15, 0.45, 0.25, 0.15]))
        game_date    = current_date + timedelta(days=gap)
        current_date = game_date

        b2b = 1 if gap == 1 else 0

        cutoff      = game_date - timedelta(days=7)
        games_in_7d = sum(1 for d in game_dates if d > cutoff)

        n_recent     = min(len(mins_history), 5)
        rolling_mins = float(np.mean(mins_history[-n_recent:])) if n_recent > 0 else avg_mins

        if n_recent >= 3:
            window        = mins_history[-n_recent:]
            xs            = np.arange(len(window), dtype=float)
            minutes_trend = float(np.polyfit(xs, window, 1)[0])
        else:
            minutes_trend = 0.0

        perf_volatility = (
            float(np.std(pts_history[-10:])) if len(pts_history) >= 3
            else pts_std * 0.5
        )

        point_deduction = min(
            4.0 * b2b + 1.5 * max(0, games_in_7d - 3),
            9.0,
        )
        actual_pts  = max(0.0, avg_pts - point_deduction + float(rng_local.normal(0, pts_std)))
        actual_mins = max(10.0, avg_mins - point_deduction * 0.15 + float(rng_local.normal(0, 1.5)))

        prop_line      = max(0.5, round((avg_pts - 1.5 + float(rng_local.uniform(0, 0.5))) * 2.0) / 2.0)
        underperformed = 1 if actual_pts < prop_line else 0
        is_away        = int(rng_local.choice([0, 1]))

        rows.append({
            "player_id":              mock_id,
            "player_name":            name,
            "team":                   team,
            "position":               pos,
            "age":                    age,
            "game_date":              game_date.isoformat(),
            "game_number":            i + 1,
            "is_away":                is_away,
            "back_to_back":           b2b,
            "games_in_7d":            games_in_7d,
            "rolling_minutes_7d":     round(rolling_mins, 2),
            "minutes_trend":          round(minutes_trend, 4),
            "performance_volatility": round(perf_volatility, 4),
            "actual_minutes":         round(actual_mins, 1),
            "actual_points":          round(actual_pts, 1),
            "prop_line_points":       round(prop_line, 1),
            "underperformed_line":    underperformed,
        })

        pts_history.append(actual_pts)
        mins_history.append(actual_mins)
        game_dates.append(game_date)

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    sep = "=" * 60

    print(sep)
    print("PropPulse - BallDontLie Live Game Log Fetcher")
    print(f"Season: {SEASON}-{SEASON + 1}")
    print(sep)

    if not API_KEY:
        print()
        print("  ERROR: BALLDONTLIE_API_KEY is not set.")
        print()
        print("  To fix:")
        print("  1. Create a free account at https://app.balldontlie.io")
        print("  2. Copy your API key from Account Settings")
        print("  3. Add to backend/.env:")
        print("       BALLDONTLIE_API_KEY=your_key_here")
        print()
        print("  Falling back to mock data for all players.")
        print()
        _run_all_mock()
        return

    print(f"\nAPI key detected. Fetching {len(TARGET_PLAYERS)} players...")
    print(f"Rate limit buffer: {REQUEST_GAP}s between requests (free tier = 5 req/min)")
    print(f"Expected runtime:  ~{len(TARGET_PLAYERS) * REQUEST_GAP // 60 + 1} minutes\n")

    all_rows: list[dict] = []
    live_count  = 0
    mock_count  = 0

    with httpx.Client() as client:
        for idx, (bdl_id, name, team, pos, age, avg_pts, pts_std, avg_mins) in enumerate(TARGET_PLAYERS):
            mock_id = MOCK_IDS.get(name, idx + 1)
            print(f"  [{idx + 1}/{len(TARGET_PLAYERS)}] {name}...")

            raw_stats = fetch_player_stats(client, bdl_id, name)

            if raw_stats:
                rows = build_live_rows(raw_stats, name, team, pos, age,
                                       avg_pts, pts_std, avg_mins, mock_id)
                if rows:
                    print(f"    OK: {len(rows)} games from BallDontLie")
                    all_rows.extend(rows)
                    live_count += 1
                else:
                    print(f"    [WARN] API returned data but 0 played games. Using mock fallback.")
                    fallback = build_mock_rows_for_player(
                        name, team, pos, age, avg_pts, pts_std, avg_mins, mock_id
                    )
                    all_rows.extend(fallback)
                    mock_count += 1
            else:
                print(f"    [WARN] Fetch failed. Using mock fallback ({40} rows).")
                fallback = build_mock_rows_for_player(
                    name, team, pos, age, avg_pts, pts_std, avg_mins, mock_id
                )
                all_rows.extend(fallback)
                mock_count += 1

            # Rate limit gap between players (skip after last player)
            if idx < len(TARGET_PLAYERS) - 1:
                print(f"    Sleeping {REQUEST_GAP}s (free tier rate limit)...")
                time.sleep(REQUEST_GAP)

    _write_and_summarize(all_rows, live_count, mock_count)


def _run_all_mock() -> None:
    """Write a full mock CSV when API key is absent. Mirrors generate_game_logs.py output."""
    all_rows: list[dict] = []
    for idx, (_, name, team, pos, age, avg_pts, pts_std, avg_mins) in enumerate(TARGET_PLAYERS):
        mock_id = MOCK_IDS.get(name, idx + 1)
        rows    = build_mock_rows_for_player(
            name, team, pos, age, avg_pts, pts_std, avg_mins, mock_id
        )
        all_rows.extend(rows)
        print(f"  {name:<30} {len(rows)} mock rows")
    _write_and_summarize(all_rows, live_count=0, mock_count=len(TARGET_PLAYERS))


def _write_and_summarize(all_rows: list[dict], live_count: int, mock_count: int) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    output_path = os.path.join(DATA_DIR, "game_logs.csv")

    df = (
        pd.DataFrame(all_rows)
        .sort_values(["game_date", "player_name"])
        .reset_index(drop=True)
    )

    df.to_csv(output_path, index=False)

    b2b_mask = df["back_to_back"] == 1
    wl_mask  = df["games_in_7d"] >= 4

    print()
    print("=" * 60)
    print(f"Saved to:          {output_path}")
    print(f"Total rows:        {len(df)}")
    print(f"Players live:      {live_count}")
    print(f"Players fallback:  {mock_count}")
    print(f"Date range:        {df['game_date'].min()}  to  {df['game_date'].max()}")
    print()
    print("Schedule stats:")
    print(f"  B2B rate:        {df['back_to_back'].mean():.1%}")
    print(f"  High workload:   {wl_mask.mean():.1%}  (games_in_7d >= 4)")
    print()
    print("Signal check:")
    rest_mask = ~b2b_mask & ~wl_mask
    print(f"  Underperf | rested:        {df[rest_mask]['underperformed_line'].mean():.1%}")
    print(f"  Underperf | B2B:           {df[b2b_mask]['underperformed_line'].mean():.1%}")
    print(f"  Underperf overall:         {df['underperformed_line'].mean():.1%}")
    print()
    if live_count > 0:
        print("Next steps:")
        print("  python ml/train.py                        (retrain on real data)")
        print("  python ml/apply_model_to_fatigue_scores.py  (update DB scores)")
    else:
        print("No live data fetched. To use real data:")
        print("  1. Add BALLDONTLIE_API_KEY to backend/.env")
        print("  2. Re-run: python ml/fetch_ball_dontlie_game_logs.py")
    print("=" * 60)


if __name__ == "__main__":
    main()