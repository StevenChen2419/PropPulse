"""
Apply the trained XGBoost risk model to all players in the database.

Run from backend/ with venv active:
    python ml/apply_model_to_fatigue_scores.py

Typical workflow:
    1. python scripts/refresh_demo_data.py      (update game times + B2B flags)
    2. python ml/apply_model_to_fatigue_scores.py  (score each player)
    3. Open http://localhost:3000/analytics      (fatigue bars reflect model)

What this does:
  - Loads risk_model.pkl and calibration params from model_meta.json
  - Reads all (Player, FatigueScore) rows from the database
  - Converts each player's fatigue profile to model features
  - Predicts calibrated underperformance probability
  - Updates fatigue_scores.fatigue_score with calibrated model output
  - Updates fatigue_scores.shap_reasons with model-driven reason text
  - Updates fatigue_scores.scored_at to current timestamp
  - Prints a before/after summary table

What this does NOT do:
  - Retrain the model
  - Delete any rows
  - Change fatigue_scores.risk_flags or workload_score
  - Require any frontend code changes
  - Run automatically on any schedule

Safe to run multiple times. Each run overwrites the previous score.

Requires:
  - docker compose up -d db   (Postgres must be running)
  - ml/models/risk_model.pkl  (run ml/train.py first)
  - ml/models/model_meta.json (run ml/train.py first)
"""

import json
import os
import pickle
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# Add backend/ to sys.path so "from app.X import Y" works.
# This script lives at backend/ml/, so go up two levels.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ML_DIR      = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, ML_DIR)

from app.database import SessionLocal
from app.models import Player, FatigueScore
from features import player_stats_to_features

MODEL_PATH = os.path.join(ML_DIR, "models", "risk_model.pkl")
META_PATH  = os.path.join(ML_DIR, "models", "model_meta.json")

# Fallback thresholds if model_meta.json has no calibration key.
FALLBACK_THRESHOLDS: dict = {"critical": 0.67, "high": 0.55, "medium": 0.45}

# Human-readable labels for each FEATURE_COLS entry.
# Only risk-raising features are shown in reasons.
REASON_LABELS: dict = {
    "back_to_back":           "Back-to-back game tonight",
    "b2b_high_workload":      "Back-to-back during a heavy week",
    "games_in_7d":            "Heavy schedule in last 7 days",
    "tired_and_away":         "Fatigued and playing away tonight",
    "heavy_minutes":          "Elevated minutes load this week",
    "high_workload":          "High game count this week",
    "rolling_minutes_7d":     "High average minutes recently",
    "minutes_trend":          "Minutes trending upward",
    "performance_volatility": "High recent performance volatility",
    "age_over_33":            "Veteran recovery factor",
}


def load_model_and_meta() -> tuple:
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(
            f"Model not found: {MODEL_PATH}\n"
            "Run: python ml/train.py"
        )
    with open(MODEL_PATH, "rb") as fh:
        model = pickle.load(fh)
    meta: dict = {}
    if os.path.exists(META_PATH):
        with open(META_PATH) as fh:
            meta = json.load(fh)
    return model, meta


def apply_calibration(raw_prob: float, meta: dict) -> float:
    cal = meta.get("calibration", {})
    if not cal or "cal_slope" not in cal:
        return raw_prob
    slope     = cal["cal_slope"]
    intercept = cal["cal_intercept"]
    return float(np.clip(slope * raw_prob + intercept, 0.0, 1.0))


def risk_label(calibrated_prob: float, meta: dict) -> str:
    cal        = meta.get("calibration", {})
    thresholds = cal.get("risk_thresholds", FALLBACK_THRESHOLDS)
    if calibrated_prob >= thresholds["critical"]: return "Critical"
    if calibrated_prob >= thresholds["high"]:     return "High"
    if calibrated_prob >= thresholds["medium"]:   return "Medium"
    return "Low"


def build_model_reasons(
    model,
    X_row:        pd.DataFrame,
    feature_cols: list,
    fs:           FatigueScore,
) -> list:
    """
    Generate reason strings using SHAP when available.
    Falls back to a feature-flag approach if SHAP fails.
    Returns at most 3 strings.
    """
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        sv        = explainer.shap_values(X_row)[0]

        # Sort by SHAP contribution (risk-raising only, val > 0.02)
        paired = sorted(zip(feature_cols, sv), key=lambda x: x[1], reverse=True)
        reasons = []
        for feat, val in paired:
            if val > 0.02 and feat in REASON_LABELS:
                reasons.append(REASON_LABELS[feat])
            if len(reasons) >= 3:
                break
        return reasons if reasons else ["No significant fatigue signals detected"]

    except Exception:
        # Fallback: derive reasons from feature values in X_row
        vals    = X_row.iloc[0]
        reasons = []
        if int(vals.get("back_to_back", 0)) == 1:
            reasons.append(REASON_LABELS["back_to_back"])
        if int(vals.get("b2b_high_workload", 0)) == 1:
            reasons.append(REASON_LABELS["b2b_high_workload"])
        elif int(vals.get("games_in_7d", 0)) >= 4:
            games = int(vals["games_in_7d"])
            reasons.append(f"Heavy schedule: {games} games in last 7 days")
        if float(vals.get("rolling_minutes_7d", 0)) > 35.0:
            mins = float(vals["rolling_minutes_7d"])
            reasons.append(f"High minutes load: {mins:.1f} avg this week")
        if not reasons:
            reasons.append("No significant fatigue signals detected")
        return reasons[:3]


def main() -> None:
    sep = "=" * 64
    print(sep)
    print("PropPulse - Apply Risk Model to fatigue_scores Table")
    print(sep)

    print("\n1. Loading model and calibration params...")
    model, meta = load_model_and_meta()
    feature_cols = meta.get("feature_cols", [])
    cal          = meta.get("calibration",  {})

    print(f"   Model trained:    {meta.get('trained_at', 'unknown')[:19]}")
    print(f"   AUC:              {meta.get('metrics', {}).get('auc', 'N/A')}")
    print(f"   Features:         {len(feature_cols)}")

    if cal:
        print(f"   Cal slope:        {cal.get('cal_slope', 'N/A')}")
        print(f"   Cal intercept:    {cal.get('cal_intercept', 'N/A')}")
        thresholds = cal.get("risk_thresholds", {})
        print(f"   Risk thresholds:  Critical>={thresholds.get('critical', '?')}  High>={thresholds.get('high', '?')}  Medium>={thresholds.get('medium', '?')}")
    else:
        print("   WARNING: No calibration in model_meta.json.")
        print("   Run: python ml/train.py  then retry.")
        print("   Continuing with uncalibrated (raw) scores.")

    print("\n2. Connecting to database...")
    db = SessionLocal()

    try:
        results = (
            db.query(FatigueScore, Player)
            .join(Player, FatigueScore.player_id == Player.id)
            .filter(Player.sport == "NBA")
            .order_by(Player.name)
            .all()
        )

        if not results:
            print("   No fatigue scores found. Run: python seed.py")
            return

        print(f"   {len(results)} players found.")

        print("\n3. Scoring all players...")
        print("-" * 64)
        print(f"  {'Player':<28} {'Old':>6}  {'Raw':>6}  {'Cal':>6}  {'Label'}")
        print("-" * 64)

        updated    = 0
        score_rows = []

        for fs, player in results:
            position = player.position or "SF"
            age      = player.age      or 28

            X_row = player_stats_to_features(
                position               = position,
                age                    = age,
                back_to_back           = bool(fs.back_to_back),
                games_in_7d            = int(fs.games_in_7d            or 0),
                rolling_minutes_7d     = float(fs.rolling_minutes_7d   or 30.0),
                minutes_trend          = float(fs.minutes_trend         or 0.0),
                performance_volatility = float(fs.performance_volatility or 0.2),
                # is_away defaults to False. We are scoring overall fatigue level,
                # not a specific upcoming game. Away status from the props table
                # is not joined here to keep the script simple and safe.
                is_away                = False,
            )

            raw_prob  = float(model.predict_proba(X_row)[:, 1][0])
            cal_prob  = apply_calibration(raw_prob, meta)
            label     = risk_label(cal_prob, meta)
            old_score = float(fs.fatigue_score or 0.0)

            new_reasons = build_model_reasons(model, X_row, feature_cols, fs)

            print(
                f"  {player.name:<28}"
                f"  {old_score:>5.0%}"
                f"  {raw_prob:>5.0%}"
                f"  {cal_prob:>5.0%}"
                f"  {label}"
            )

            # Write updated values back to the row in memory.
            # db.commit() below persists all of these at once.
            fs.fatigue_score = round(cal_prob, 4)
            fs.shap_reasons  = new_reasons
            fs.scored_at     = datetime.utcnow()

            score_rows.append({
                "name":  player.name,
                "old":   old_score,
                "raw":   raw_prob,
                "cal":   cal_prob,
                "label": label,
            })
            updated += 1

        db.commit()
        print("-" * 64)

        print(f"\n4. Committed {updated} updates to fatigue_scores.")

        # Summary statistics
        cals    = [r["cal"] for r in score_rows]
        labels  = [r["label"] for r in score_rows]
        print(f"\n   Score summary (calibrated):")
        print(f"   Min:      {min(cals):.0%}")
        print(f"   Max:      {max(cals):.0%}")
        print(f"   Mean:     {sum(cals)/len(cals):.0%}")
        for tier in ["Critical", "High", "Medium", "Low"]:
            count = labels.count(tier)
            print(f"   {tier:<10} {count} player{'s' if count != 1 else ''}")

        print(f"\n   Verify in the API:")
        print(f"   curl http://localhost:8000/rankings/fatigue-leaderboard")
        print(f"\n   Verify in the app:")
        print(f"   http://localhost:3000/analytics")
        print("")
        print(sep)

    except Exception as exc:
        db.rollback()
        print(f"\nError: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
