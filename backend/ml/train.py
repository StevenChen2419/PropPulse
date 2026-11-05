"""
Train the PropPulse XGBoost performance risk model.

Run from backend/ with venv active:
    python ml/generate_game_logs.py   (only needed if game_logs.csv is stale)
    python ml/train.py

Artifacts saved to ml/models/:
    risk_model.pkl      Trained XGBoost classifier
    feature_cols.json   Ordered feature column list
    model_meta.json     Metrics, calibration params, training context

Day 10 addition: output calibration.
After training, we compute two anchor predictions on the full dataset:
  - Median raw probability for rested games (back_to_back=0, games_in_7d<=3)
  - Median raw probability for B2B games (back_to_back=1)

A linear map sends: rested_median -> 0.28, b2b_median -> 0.68.
This is a monotonic transformation so AUC is preserved exactly.
The calibration params are saved to model_meta.json so predict_risk.py
and apply_model_to_fatigue_scores.py can apply the same transformation.
"""

import json
import os
import pickle
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
import xgboost as xgb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from features import FEATURE_COLS, build_features

ML_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_PATH  = os.path.join(ML_DIR, "data",   "game_logs.csv")
MODEL_DIR  = os.path.join(ML_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "risk_model.pkl")
COLS_PATH  = os.path.join(MODEL_DIR, "feature_cols.json")
META_PATH  = os.path.join(MODEL_DIR, "model_meta.json")

TARGET_COL = "underperformed_line"
TRAIN_FRAC = 0.80

# Calibration target values.
# Rested games (no B2B, low workload) should predict near 0.28 (Low risk).
# B2B games should predict near 0.68 (Critical/High risk).
# Adjust these if the risk label distribution feels too aggressive or too soft.
CAL_TARGET_RESTED = 0.28
CAL_TARGET_B2B    = 0.68


def load_data() -> pd.DataFrame:
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(
            f"Game logs not found: {DATA_PATH}\n"
            "Run: python ml/generate_game_logs.py"
        )
    df = pd.read_csv(DATA_PATH)
    return df.sort_values(["game_date", "player_name"]).reset_index(drop=True)


def validate_signal(df: pd.DataFrame) -> None:
    b2b     = df[df["back_to_back"] == 1][TARGET_COL].mean()
    non_b2b = df[df["back_to_back"] == 0][TARGET_COL].mean()
    diff    = b2b - non_b2b

    print(f"   B2B underperf:     {b2b:.1%}")
    print(f"   Non-B2B underperf: {non_b2b:.1%}")
    print(f"   Diff:              {diff:+.1%}")

    if diff < 0.10:
        raise ValueError(
            f"\nSignal too weak (diff={diff:+.1%}, need >=0.10).\n"
            "Re-run: python ml/generate_game_logs.py"
        )
    print("   Signal: OK" if diff >= 0.15 else "   Signal: marginal but acceptable")


def temporal_split(df: pd.DataFrame) -> tuple:
    cutoff = int(len(df) * TRAIN_FRAC)
    return df.iloc[:cutoff].copy(), df.iloc[cutoff:].copy()


def train_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test:  pd.DataFrame,
    y_test:  pd.Series,
) -> xgb.XGBClassifier:
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    return model


def evaluate(model: xgb.XGBClassifier, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    proba = model.predict_proba(X_test)[:, 1]
    pred  = model.predict(X_test)
    return {
        "auc":      round(float(roc_auc_score(y_test, proba)), 4),
        "accuracy": round(float(accuracy_score(y_test, pred)),  4),
        "log_loss": round(float(log_loss(y_test, proba)),        4),
    }


def compute_calibration(model: xgb.XGBClassifier, df: pd.DataFrame) -> dict:
    """
    Compute linear calibration anchored at two empirical medians.

    We use the FULL dataset (not just test) for stable median estimates.
    With seed 42 and 1640 rows this produces consistent values every run.

    The linear map is: calibrated = slope * raw + intercept
    Clipped to [0, 1] before use.

    Risk thresholds are defined on the CALIBRATED scale, not the raw scale.
    They are saved here so every downstream script uses the same boundaries.
    """
    X_all     = build_features(df)
    proba_all = model.predict_proba(X_all)[:, 1]

    rested_mask = ((df["back_to_back"] == 0) & (df["games_in_7d"] <= 3)).values
    b2b_mask    = (df["back_to_back"] == 1).values

    rested_median = float(np.median(proba_all[rested_mask]))
    b2b_median    = float(np.median(proba_all[b2b_mask]))

    if b2b_median <= rested_median:
        print("   WARNING: B2B median <= rested median. Using identity calibration.")
        slope, intercept = 1.0, 0.0
    else:
        slope     = (CAL_TARGET_B2B - CAL_TARGET_RESTED) / (b2b_median - rested_median)
        intercept = CAL_TARGET_RESTED - slope * rested_median

    return {
        "rested_anchor_raw": round(rested_median, 4),
        "b2b_anchor_raw":    round(b2b_median, 4),
        "cal_slope":         round(slope, 4),
        "cal_intercept":     round(intercept, 4),
        "cal_target_rested": CAL_TARGET_RESTED,
        "cal_target_b2b":    CAL_TARGET_B2B,
        # Thresholds on CALIBRATED scale.
        # Critical and High use values close to or above CAL_TARGET_B2B (0.68).
        # Medium sits between rested (0.28) and High.
        "risk_thresholds": {
            "critical": 0.60,
            "high":     0.47,
            "medium":   0.38,
        },
    }


def print_calibration(cal: dict) -> None:
    slope     = cal["cal_slope"]
    intercept = cal["cal_intercept"]
    thresholds = cal["risk_thresholds"]

    print(f"   Rested median (raw):  {cal['rested_anchor_raw']:.4f}  ->  calibrated {CAL_TARGET_RESTED:.2f}")
    print(f"   B2B median (raw):     {cal['b2b_anchor_raw']:.4f}  ->  calibrated {CAL_TARGET_B2B:.2f}")
    print(f"   Transform:            cal = {slope:.3f} * raw + ({intercept:.3f})")
    print(f"   Risk thresholds (calibrated scale):")
    print(f"     Critical >= {thresholds['critical']}")
    print(f"     High     >= {thresholds['high']}")
    print(f"     Medium   >= {thresholds['medium']}")
    print(f"     Low       < {thresholds['medium']}")

    print("\n   Calibration spot-check:")
    for raw_ex, label in [
        (cal["rested_anchor_raw"],  "rested median"),
        (0.50,                      "mid-range"),
        (cal["b2b_anchor_raw"],     "B2B median"),
    ]:
        cal_val = float(np.clip(slope * raw_ex + intercept, 0, 1))
        risk    = "Critical" if cal_val >= 0.60 else \
                  "High"     if cal_val >= 0.47 else \
                  "Medium"   if cal_val >= 0.38 else "Low"
        print(f"     raw {raw_ex:.3f} -> calibrated {cal_val:.3f}  ({risk})  [{label}]")


def print_importances(model: xgb.XGBClassifier) -> None:
    pairs = sorted(
        zip(FEATURE_COLS, model.feature_importances_),
        key=lambda x: x[1],
        reverse=True,
    )
    print("\n  Feature importances (gain):")
    for feat, score in pairs:
        bar = "#" * int(score * 60)
        print(f"    {feat:<28}  {score:.4f}  {bar}")


def print_group_breakdown(model: xgb.XGBClassifier, df: pd.DataFrame, X: pd.DataFrame) -> None:
    proba = model.predict_proba(X)[:, 1]
    dfc   = df.copy()
    dfc["predicted_risk"] = proba

    b2b_mask  = dfc["back_to_back"] == 1
    wl_mask   = dfc["games_in_7d"]  >= 4
    both_mask = b2b_mask & wl_mask
    rest_mask = ~b2b_mask & ~wl_mask

    print("\n  Predicted risk by group (raw, before calibration):")
    groups = [
        ("Rested (no B2B, low workload)", rest_mask),
        ("High workload only",            wl_mask & ~b2b_mask),
        ("B2B only",                      b2b_mask & ~wl_mask),
        ("B2B + high workload",           both_mask),
    ]
    for label, mask in groups:
        if mask.sum() > 0:
            avg = dfc.loc[mask, "predicted_risk"].mean()
            print(f"    {label:<32}  avg raw {avg:.1%}")


def print_shap_sample(model: xgb.XGBClassifier, X_test: pd.DataFrame) -> None:
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        sample    = X_test.iloc[:3]
        shap_vals = explainer.shap_values(sample)

        print("\n  SHAP explanations (3 test samples, raw probabilities):")
        for i in range(len(sample)):
            sv       = shap_vals[i]
            raw_prob = float(model.predict_proba(sample.iloc[[i]])[:, 1][0])
            top3     = sorted(zip(FEATURE_COLS, sv), key=lambda x: abs(x[1]), reverse=True)[:3]
            print(f"\n    Sample {i + 1} - raw {raw_prob:.0%}")
            for feat, val in top3:
                direction = "raises" if val > 0 else "lowers"
                print(f"      {feat}: {direction} risk  (SHAP {val:+.3f})")

    except Exception as exc:
        print(f"\n  SHAP unavailable ({exc}). See feature importances above.")


def main() -> None:
    os.makedirs(MODEL_DIR, exist_ok=True)

    sep = "=" * 58
    print(sep)
    print("PropPulse - Performance Risk Model Training")
    print(sep)

    print("\n1. Loading data...")
    df = load_data()
    print(f"   Rows:    {len(df)}")
    print(f"   Players: {df['player_name'].nunique()}")
    print(f"   Dates:   {df['game_date'].min()}  to  {df['game_date'].max()}")
    print(f"   Target:  {df[TARGET_COL].mean():.1%} underperformance rate")

    print("\n2. Validating signal...")
    validate_signal(df)

    print(f"\n3. Features ({len(FEATURE_COLS)}):")
    print(f"   {FEATURE_COLS}")

    print("\n4. Temporal split (80/20)...")
    df_train, df_test = temporal_split(df)
    X_train = build_features(df_train)
    X_test  = build_features(df_test)
    y_train = df_train[TARGET_COL]
    y_test  = df_test[TARGET_COL]
    print(f"   Train: {len(X_train)} rows  ({df_train['game_date'].min()} to {df_train['game_date'].max()})")
    print(f"   Test:  {len(X_test)} rows   ({df_test['game_date'].min()} to {df_test['game_date'].max()})")

    print("\n5. Training XGBoost...")
    model = train_model(X_train, y_train, X_test, y_test)
    print("   Done.")

    print("\n6. Evaluating on test set...")
    metrics = evaluate(model, X_test, y_test)
    print(f"   AUC:      {metrics['auc']:.4f}  (target: > 0.63)")
    print(f"   Accuracy: {metrics['accuracy']:.4f}")
    print(f"   Log loss: {metrics['log_loss']:.4f}")
    if metrics["auc"] < 0.60:
        print("\n   WARNING: AUC below 0.60. Check signal validation output.")

    print_importances(model)
    print_group_breakdown(model, df_test, X_test)
    print_shap_sample(model, X_test)

    print("\n7. Computing output calibration (Day 10)...")
    calibration = compute_calibration(model, df)
    print_calibration(calibration)

    print("\n8. Saving artifacts...")
    with open(MODEL_PATH, "wb") as fh:
        pickle.dump(model, fh)
    with open(COLS_PATH, "w") as fh:
        json.dump(FEATURE_COLS, fh, indent=2)

    meta: dict = {
        "trained_at":   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_train":      len(X_train),
        "n_test":       len(X_test),
        "n_features":   len(FEATURE_COLS),
        "feature_cols": FEATURE_COLS,
        "metrics":      metrics,
        "calibration":  calibration,
        "model_params": {
            "n_estimators":     200,
            "max_depth":        4,
            "learning_rate":    0.05,
            "subsample":        0.80,
            "colsample_bytree": 0.80,
            "min_child_weight": 3,
        },
    }
    with open(META_PATH, "w") as fh:
        json.dump(meta, fh, indent=2)

    print(f"   Model:    {MODEL_PATH}")
    print(f"   Features: {COLS_PATH}")
    print(f"   Metadata: {META_PATH}")
    print("")
    print(sep)
    print("Training complete.")
    print("Next: python ml/predict_risk.py")
    print(sep)


if __name__ == "__main__":
    main()