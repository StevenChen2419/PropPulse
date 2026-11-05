"""
Load trained PropPulse risk model and run calibrated predictions
on sample player scenarios.

Run from backend/ with venv active:
    python ml/predict_risk.py

Requires ml/models/risk_model.pkl and ml/models/model_meta.json.
Run ml/train.py first if either is missing.

Day 10 changes:
- Loads calibration params from model_meta.json.
- Applies linear calibration before computing risk label.
- Lillard scenario corrected: B2B removed, games_in_7d=4 (workload only).
  B2B is a Critical signal; a genuinely Medium scenario should not have it.
- Both raw and calibrated scores shown for transparency.
"""

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from features import FEATURE_COLS, player_stats_to_features

ML_DIR     = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(ML_DIR, "models", "risk_model.pkl")
META_PATH  = os.path.join(ML_DIR, "models", "model_meta.json")

# Fallback thresholds used when model_meta.json has no calibration key.
# These are on the RAW probability scale.
FALLBACK_THRESHOLDS: dict = {"critical": 0.67, "high": 0.55, "medium": 0.45}

# Sample scenarios. Each mirrors a seed-data player fatigue profile.
# Expected ordering: LeBron/Embiid > Lillard > Jokic/SGA.
SAMPLE_SCENARIOS = [
    {
        "label":                 "LeBron James   Critical  (B2B, 4 games/7d, 38.5 avg mins, age 39)",
        "position":              "SF",
        "age":                   39,
        "back_to_back":          True,
        "games_in_7d":           4,
        "rolling_minutes_7d":    38.5,
        "minutes_trend":         0.15,
        "performance_volatility": 0.30,
        "is_away":               True,
    },
    {
        "label":                 "Joel Embiid    Critical  (B2B, 5 games/7d, high volatility)",
        "position":              "C",
        "age":                   30,
        "back_to_back":          True,
        "games_in_7d":           5,
        "rolling_minutes_7d":    34.5,
        "minutes_trend":         0.25,
        "performance_volatility": 0.40,
        "is_away":               True,
    },
    {
        # Corrected from Day 9: B2B removed. Workload (4 games) + slightly
        # elevated minutes is genuinely Medium, not Critical.
        "label":                 "Damian Lillard Medium    (no B2B, 4 games/7d, heavy workload)",
        "position":              "PG",
        "age":                   33,
        "back_to_back":          False,
        "games_in_7d":           4,
        "rolling_minutes_7d":    35.5,
        "minutes_trend":         0.08,
        "performance_volatility": 0.28,
        "is_away":               True,
    },
    {
        "label":                 "Nikola Jokic   Low       (rested, normal workload, home)",
        "position":              "C",
        "age":                   29,
        "back_to_back":          False,
        "games_in_7d":           3,
        "rolling_minutes_7d":    31.5,
        "minutes_trend":         -0.10,
        "performance_volatility": 0.15,
        "is_away":               False,
    },
    {
        "label":                 "Shai G-A       Low       (young, fresh, declining load)",
        "position":              "PG",
        "age":                   26,
        "back_to_back":          False,
        "games_in_7d":           3,
        "rolling_minutes_7d":    33.5,
        "minutes_trend":         -0.05,
        "performance_volatility": 0.18,
        "is_away":               False,
    },
]


def load_model():
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(
            f"Model not found: {MODEL_PATH}\n"
            "Run: python ml/train.py"
        )
    with open(MODEL_PATH, "rb") as fh:
        return pickle.load(fh)


def load_meta() -> dict:
    if not os.path.exists(META_PATH):
        return {}
    with open(META_PATH) as fh:
        return json.load(fh)


def apply_calibration(raw_prob: float, meta: dict) -> float:
    """
    Apply the linear calibration saved in model_meta.json.
    If calibration params are missing (old model artifact), returns raw_prob.
    Clipped to [0, 1].
    """
    cal = meta.get("calibration", {})
    if not cal or "cal_slope" not in cal:
        return raw_prob
    slope     = cal["cal_slope"]
    intercept = cal["cal_intercept"]
    return float(np.clip(slope * raw_prob + intercept, 0.0, 1.0))


def risk_label(calibrated_prob: float, meta: dict) -> str:
    """
    Map calibrated probability to a human-readable risk tier.
    Uses thresholds from model_meta.json (calibrated scale).
    Falls back to FALLBACK_THRESHOLDS on raw scale if no calibration.
    """
    cal        = meta.get("calibration", {})
    thresholds = cal.get("risk_thresholds", FALLBACK_THRESHOLDS)
    if calibrated_prob >= thresholds["critical"]: return "Critical"
    if calibrated_prob >= thresholds["high"]:     return "High"
    if calibrated_prob >= thresholds["medium"]:   return "Medium"
    return "Low"


def explain(model, X_row: pd.DataFrame, scenario: dict, meta: dict) -> None:
    raw_prob = float(model.predict_proba(X_row)[:, 1][0])
    cal_prob = apply_calibration(raw_prob, meta)
    label    = risk_label(cal_prob, meta)

    filled = int(cal_prob * 30)
    bar    = "#" * filled + "-" * (30 - filled)

    print(f"\n  {scenario['label']}")
    print(f"  Raw: {raw_prob:.0%}   Calibrated: {cal_prob:.0%}  [{bar}]  {label}")

    try:
        import shap
        explainer = shap.TreeExplainer(model)
        sv        = explainer.shap_values(X_row)[0]

        top3 = sorted(zip(FEATURE_COLS, sv), key=lambda x: abs(x[1]), reverse=True)[:3]
        print("  Top factors (SHAP):")
        for feat, val in top3:
            direction = "raises" if val > 0 else "lowers"
            raw_val   = float(X_row[feat].iloc[0])
            print(f"    {feat} = {raw_val}  ->  {direction} risk  (SHAP {val:+.3f})")

    except Exception:
        # Fallback: plain flag-based signals
        vals  = X_row.iloc[0]
        flags = []
        if int(vals.get("back_to_back", 0)):
            flags.append("back_to_back = 1  (strongest signal)")
        if int(vals.get("b2b_high_workload", 0)):
            flags.append("b2b_high_workload = 1  (compounding signal)")
        if int(vals.get("games_in_7d", 0)) >= 4:
            flags.append(f"games_in_7d = {int(vals['games_in_7d'])}  (heavy week)")
        if float(vals.get("rolling_minutes_7d", 0)) > 34:
            flags.append(f"rolling_minutes_7d = {float(vals['rolling_minutes_7d']):.1f}  (elevated)")
        if int(vals.get("age_over_33", 0)):
            flags.append("age_over_33 = 1  (veteran recovery factor)")
        if not flags:
            flags.append("no major fatigue flags  (low risk profile)")
        print("  Key signals:")
        for flag in flags:
            print(f"    - {flag}")


def main() -> None:
    sep = "=" * 62
    print(sep)
    print("PropPulse - Calibrated Performance Risk Predictions")
    print(sep)

    model = load_model()
    meta  = load_meta()

    if not meta.get("calibration"):
        print(
            "\n  WARNING: No calibration found in model_meta.json.\n"
            "  Run: python ml/train.py  (adds calibration metadata)\n"
            "  Showing raw probabilities with fallback thresholds.\n"
        )
    else:
        m   = meta.get("metrics",      {})
        cal = meta.get("calibration",  {})
        print(f"\nModel trained:         {meta.get('trained_at', 'unknown')[:19]}")
        print(f"AUC (test set):        {m.get('auc', 'N/A')}")
        print(f"Features:              {meta.get('n_features', '?')}")
        print(f"Cal rested anchor:     raw {cal.get('rested_anchor_raw', '?')}  -> calibrated {cal.get('cal_target_rested', '?')}")
        print(f"Cal B2B anchor:        raw {cal.get('b2b_anchor_raw',    '?')}  -> calibrated {cal.get('cal_target_b2b',    '?')}")
        print(f"Cal transform:         {cal.get('cal_slope', '?')} * raw + ({cal.get('cal_intercept', '?')})")

    print(f"\nRunning {len(SAMPLE_SCENARIOS)} scenarios...")
    print("-" * 62)

    for scenario in SAMPLE_SCENARIOS:
        X_row = player_stats_to_features(
            position               = scenario["position"],
            age                    = scenario["age"],
            back_to_back           = scenario["back_to_back"],
            games_in_7d            = scenario["games_in_7d"],
            rolling_minutes_7d     = scenario["rolling_minutes_7d"],
            minutes_trend          = scenario["minutes_trend"],
            performance_volatility = scenario["performance_volatility"],
            is_away                = scenario["is_away"],
        )
        explain(model, X_row, scenario, meta)

    print("\n")
    print(sep)
    print("Scenario targets (calibrated):")
    print("  LeBron / Embiid  ->  58-78%  Critical")
    print("  Lillard          ->  45-58%  Medium or High")
    print("  Jokic / SGA      ->  22-38%  Low")
    print("")
    print("Next: python ml/apply_model_to_fatigue_scores.py")
    print(sep)


if __name__ == "__main__":
    main()