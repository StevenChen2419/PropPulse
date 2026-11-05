"""
Refresh demo prop data for PropPulse.

Run from the backend/ directory with venv activated:
    python scripts/refresh_demo_data.py

What this does:
- Sets all prop game_times to upcoming slots today (1 to 9 hours from now).
- Saves old line to line_24h_ago, shifts line slightly to simulate movement.
- Keeps all props active.
- Randomly updates back_to_back flags (roughly 30% of players).
- Recalculates fatigue scores based on updated flags.

What this does NOT do:
- Delete or reseed props. Existing prop IDs stay the same.
- Delete interactions, saved props, or slip items.
- Break any existing user data.

Requires PROPPULSE_DEMO_MODE=true and a separate proppulse_demo database.
Provider-backed and unmarked legacy data are refused before any writes.
"""

import sys
import os

# Insert backend/ into sys.path so "from app.X import Y" works.
# This script lives at backend/scripts/, so we go up two levels.
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import random
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.models import Prop, FatigueScore
from app.services.demo_guard import require_demo_dataset, require_demo_environment

# Spread game times across today. NBA games typically tip at 7pm, 7:30, 8pm, 10pm ET.
# For demo purposes we use hours-from-now so the board always looks live.
GAME_SLOTS_HOURS = [1, 2, 3, 4, 5, 6, 7, 8, 9]

# Line shifts applied randomly to simulate overnight movement.
# Values are in 0.5 increments to match how sportsbooks set lines.
LINE_SHIFTS = [-1.5, -1.0, -0.5, -0.5, 0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.5]


def refresh_props(db) -> int:
    require_demo_dataset(db)
    props = db.query(Prop).all()
    now = datetime.utcnow()

    for prop in props:
        # Set game_time to an upcoming slot today.
        hours = random.choice(GAME_SLOTS_HOURS)
        minutes = random.randint(0, 30)
        prop.game_time = now + timedelta(hours=hours, minutes=minutes)

        # Simulate line movement. Save the current line as yesterday's line,
        # then apply a small random shift to the new line.
        shift = random.choice(LINE_SHIFTS)
        prop.line_24h_ago = prop.line
        new_line = round((prop.line + shift) * 2) / 2  # keep X.0 or X.5
        prop.line = max(0.5, new_line)  # never below 0.5

        # Small popularity drift to keep rankings interesting.
        prop.popularity_count = max(0, prop.popularity_count + random.randint(-3, 8))

        # Ensure all props are visible.
        prop.is_active = True

    db.commit()
    return len(props)


def refresh_fatigue(db) -> int:
    require_demo_dataset(db)
    scores = db.query(FatigueScore).all()

    for fs in scores:
        was_b2b = fs.back_to_back

        # Roughly 30% of players are on a back-to-back on any given night.
        # This is close to the real NBA rate during a dense schedule.
        fs.back_to_back = random.random() < 0.30

        # Update risk flags to match the new back_to_back value.
        flags = list(fs.risk_flags or [])
        reasons = list(fs.shap_reasons or [])

        if fs.back_to_back and not was_b2b:
            if "back-to-back" not in flags:
                flags.insert(0, "back-to-back")
            if "Back-to-back game tonight" not in reasons:
                reasons.insert(0, "Back-to-back game tonight")
        elif not fs.back_to_back and was_b2b:
            flags   = [f for f in flags   if f != "back-to-back"]
            reasons = [r for r in reasons if r != "Back-to-back game tonight"]

        fs.risk_flags   = flags
        fs.shap_reasons = reasons

        # Recalculate the composite fatigue score from flags and stats.
        score = 0.0
        if fs.back_to_back:                      score += 0.30
        if fs.games_in_7d >= 5:                  score += 0.25
        elif fs.games_in_7d == 4:                score += 0.15
        if fs.rolling_minutes_7d > 36:           score += 0.20
        elif fs.rolling_minutes_7d > 33:         score += 0.10
        if fs.minutes_trend > 0.15:              score += 0.10
        if fs.performance_volatility > 0.35:     score += 0.15
        fs.fatigue_score = min(1.0, round(score, 3))
        fs.scored_at = datetime.utcnow()

    db.commit()
    return len(scores)


def print_summary(db):
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=2)

    active_total    = db.query(Prop).filter(Prop.is_active == True).count()
    upcoming_count  = db.query(Prop).filter(
        Prop.is_active == True,
        Prop.game_time >= cutoff
    ).count()
    b2b_count       = db.query(FatigueScore).filter(
        FatigueScore.back_to_back == True
    ).count()

    with_movement = db.query(Prop).filter(
        Prop.is_active == True,
        Prop.line_24h_ago != None,
        Prop.line != Prop.line_24h_ago
    ).count()

    print("")
    print("  Refresh summary")
    print(f"  Active props:       {active_total}")
    print(f"  Upcoming (2h):      {upcoming_count}")
    print(f"  Props with movement: {with_movement}")
    print(f"  B2B players:        {b2b_count}")
    print(f"  Refreshed at:       {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print("")


def main():
    print("PropPulse demo data refresh starting...")
    from app.database import engine
    require_demo_environment(engine)
    db = SessionLocal()
    try:
        prop_count    = refresh_props(db)
        fatigue_count = refresh_fatigue(db)
        print(f"  Props refreshed:    {prop_count}")
        print(f"  Fatigue refreshed:  {fatigue_count}")
        print_summary(db)
        print("Done. Restart the backend or wait for the feed to reload.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
