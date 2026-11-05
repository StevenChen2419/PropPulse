"""
Generate a reproducible mock NBA game log dataset for XGBoost training.

Three root-cause fixes vs Day 8:

1. Block-based scheduling replaces uniform random gaps.
   Road-trip blocks (1-2 day gaps) and rest blocks (3-5 day gaps) create
   the schedule clusters that produce a realistic B2B rate (~20%) and
   high-workload rate (~25%), vs 19.5% B2B but only 6.6% high-workload
   in Day 8.

2. Prop line is now set at approximately the player's season average,
   NOT at rolling recent form. This is the critical fix. When the line
   adapts to a fatigued player's recent low scores, fatigue no longer
   causes underperformance relative to the line - the model has no signal
   to learn. A stable line preserves the signal.

3. Fatigue penalty uses flat point deductions (not percentages).
   B2B costs 4.0 points regardless of scoring average. With pts_std ~5,
   signal-to-noise ratio is 0.8, which is learnable. The original 7%
   penalty gave only 0.35 signal-to-noise.

Run from backend/ with venv active:
    python ml/generate_game_logs.py

Output: ml/data/game_logs.csv
"""

import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

RANDOM_SEED      = 42
rng              = np.random.default_rng(RANDOM_SEED)
SEASON_START     = date(2023, 10, 24)
GAMES_PER_PLAYER = 82
DATA_DIR         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# (player_id, name, team, position, age, avg_pts, pts_std, avg_mins)
PLAYER_PROFILES = [
    ( 1, "LeBron James",            "LAL", "SF", 39, 24.5, 5.0, 34.5),
    ( 2, "Stephen Curry",           "GSW", "PG", 36, 27.5, 6.0, 32.0),
    ( 3, "Nikola Jokic",            "DEN", "C",  29, 26.0, 5.5, 31.5),
    ( 4, "Luka Doncic",             "DAL", "PG", 25, 28.0, 6.5, 36.0),
    ( 5, "Giannis Antetokounmpo",   "MIL", "PF", 29, 30.0, 6.0, 32.0),
    ( 6, "Kevin Durant",            "PHX", "SF", 35, 27.0, 5.5, 34.0),
    ( 7, "Joel Embiid",             "PHI", "C",  30, 34.0, 7.0, 31.0),
    ( 8, "Jayson Tatum",            "BOS", "SF", 26, 27.0, 5.5, 35.5),
    ( 9, "Damian Lillard",          "MIL", "PG", 33, 24.0, 5.5, 34.0),
    (10, "Anthony Davis",           "LAL", "C",  31, 24.0, 6.0, 35.0),
    (11, "Shai Gilgeous-Alexander", "OKC", "PG", 26, 31.0, 5.5, 34.5),
    (12, "Donovan Mitchell",        "CLE", "SG", 27, 26.0, 5.5, 33.5),
    (13, "Devin Booker",            "PHX", "SG", 27, 27.0, 5.5, 33.5),
    (14, "Tyrese Haliburton",       "IND", "PG", 24, 20.0, 5.0, 32.5),
    (15, "Ja Morant",               "MEM", "PG", 24, 25.0, 6.0, 31.5),
    (16, "Bam Adebayo",             "MIA", "C",  26, 20.0, 4.5, 32.5),
    (17, "Anthony Edwards",         "MIN", "SG", 22, 25.0, 6.0, 34.5),
    (18, "Cade Cunningham",         "DET", "PG", 23, 22.0, 5.5, 33.5),
    (19, "Paolo Banchero",          "ORL", "PF", 21, 22.0, 5.5, 33.0),
    (20, "Victor Wembanyama",       "SAS", "C",  20, 21.0, 7.0, 28.5),
]


def make_schedule(n_games: int) -> list:
    """
    Block-based NBA schedule. Three segment types create realistic clusters:

    Dense block (35% prob):  3-5 games, 1-2 day gaps  -- road trip / B2B stretch
    Normal block (37% prob): 2-3 games, 2-3 day gaps  -- typical home stand
    Rest block (28% prob):   1-2 games, 3-5 day gaps  -- All-Star break / long road gap

    With seed 42 this produces:
    - B2B rate ~20% (vs 19.5% uniform but only 6.6% workload in Day 8)
    - games_in_7d >= 4 rate ~25% (vs 6.6% in Day 8)
    - Season span ~165-175 days (realistic NBA season)
    """
    dates = [SEASON_START]
    added = 1

    while added < n_games:
        remaining = n_games - added
        r         = float(rng.random())

        if r < 0.35 and remaining >= 3:
            # Dense block: road trip / B2B stretch
            block = min(int(rng.integers(3, 6)), remaining)
            for _ in range(block):
                gap = int(rng.choice([1, 2], p=[0.55, 0.45]))
                dates.append(dates[-1] + timedelta(days=gap))
            added += block

        elif r < 0.72 and remaining >= 2:
            # Normal block: home stand
            block = min(int(rng.integers(2, 4)), remaining)
            for _ in range(block):
                gap = int(rng.choice([2, 3], p=[0.60, 0.40]))
                dates.append(dates[-1] + timedelta(days=gap))
            added += block

        else:
            # Rest block: long break
            block = min(int(rng.integers(1, 3)), remaining)
            for _ in range(block):
                gap = int(rng.choice([3, 4, 5], p=[0.50, 0.35, 0.15]))
                dates.append(dates[-1] + timedelta(days=gap))
            added += block

    return dates[:n_games]


def build_player_rows(profile: tuple, dates: list) -> list:
    """
    Build one game row per date for a single player.

    Fatigue deduction table (flat points, not percentages):
      B2B game:               -4.0 pts  (strongest single signal)
      Extra game above 3/7d:  -1.5 pts  (workload accumulation)
      Heavy minutes (>35):    -1.0 pts  (physical toll)
      Age above 33:           -0.5 pts per year (veteran recovery cost)
      Cap:                     9.0 pts

    With pts_std ~5 pts, B2B gives signal-to-noise ~0.8 vs prop_line.
    That is sufficient for XGBoost to learn with ~1300 training rows.

    Prop line = avg_pts - 1.25 (center of uniform range) + tiny noise.
    NOT based on rolling form. This preserves the fatigue signal.
    Expected underperformance without fatigue: ~40%.
    Expected underperformance on B2B: ~72-76%.
    """
    pid, name, team, pos, age, avg_pts, pts_std, avg_mins = profile

    rows: list         = []
    pts_history: list  = []
    mins_history: list = []

    for i, game_date in enumerate(dates):

        # Back-to-back: previous game was exactly one day ago
        b2b = 1 if (i > 0 and (game_date - dates[i - 1]).days == 1) else 0

        # Rolling 7-day game count (prior games only, no today)
        cutoff      = game_date - timedelta(days=7)
        games_in_7d = sum(1 for d in dates[:i] if d > cutoff)

        # Rolling load features from prior games only (no lookahead)
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

        is_away = int(rng.choice([0, 1]))

        # Flat point deductions: consistent signal regardless of scoring average
        point_deduction = (
            4.0 * b2b
            + 1.5 * max(0, games_in_7d - 3)
            + 1.0 * int(rolling_mins > 35.0)
            + 0.5 * max(0, age - 33)
        )
        point_deduction = min(point_deduction, 9.0)

        actual_mins = max(
            10.0,
            avg_mins - point_deduction * 0.15 + float(rng.normal(0, 1.5)),
        )
        actual_pts = max(
            0.0,
            avg_pts - point_deduction + float(rng.normal(0, pts_std)),
        )

        # Prop line: stable at approximately season average.
        # Range: avg_pts - 1.5 to avg_pts - 1.0 (avg_pts - 1.25 center).
        # NOT updated from rolling form. This is the fix for Day 8.
        prop_line = max(
            0.5,
            round((avg_pts - 1.5 + float(rng.uniform(0, 0.5))) * 2.0) / 2.0,
        )

        underperformed = 1 if actual_pts < prop_line else 0

        rows.append({
            "player_id":              pid,
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

    return rows


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    output_path = os.path.join(DATA_DIR, "game_logs.csv")

    print("Generating mock NBA game logs...")
    print(f"  Players:          {len(PLAYER_PROFILES)}")
    print(f"  Games per player: {GAMES_PER_PLAYER}")
    print(f"  Random seed:      {RANDOM_SEED}")
    print("")

    all_rows: list = []
    for profile in PLAYER_PROFILES:
        dates = make_schedule(GAMES_PER_PLAYER)
        rows  = build_player_rows(profile, dates)
        all_rows.extend(rows)
        print(f"  {profile[1]:<30} {len(rows)} games")

    df = (
        pd.DataFrame(all_rows)
        .sort_values(["game_date", "player_name"])
        .reset_index(drop=True)
    )

    df.to_csv(output_path, index=False)

    b2b_mask  = df["back_to_back"] == 1
    wl_mask   = df["games_in_7d"] >= 4
    both_mask = b2b_mask & wl_mask
    rest_mask = ~b2b_mask & ~wl_mask

    print("")
    print(f"Saved to:             {output_path}")
    print(f"Total rows:           {len(df)}")
    print(f"Date range:           {df['game_date'].min()}  to  {df['game_date'].max()}")
    print("")
    print("Schedule stats (targets: B2B ~20%, high workload ~25%):")
    print(f"  B2B rate:           {df['back_to_back'].mean():.1%}")
    print(f"  High workload rate: {wl_mask.mean():.1%}  (games_in_7d >= 4)")
    print("")
    print("Signal check - diff proves the model has something to learn:")
    print(f"  Underperf | rested:        {df[rest_mask]['underperformed_line'].mean():.1%}  (target ~40%)")
    print(f"  Underperf | high workload: {df[wl_mask]['underperformed_line'].mean():.1%}  (target ~60%)")
    print(f"  Underperf | B2B:           {df[b2b_mask]['underperformed_line'].mean():.1%}  (target ~72%)")
    print(f"  Underperf | both:          {df[both_mask]['underperformed_line'].mean():.1%}  (target ~82%)")
    print(f"  Underperf overall:         {df['underperformed_line'].mean():.1%}  (target 45-52%)")
    print("")
    print("Next: python ml/train.py")


if __name__ == "__main__":
    main()