"""
Feature engineering for the PropPulse performance risk model.

Single source of truth for FEATURE_COLS, build_features(), and
player_stats_to_features(). Both train.py and API inference routes
import from here to guarantee training and serving use identical features.

Changes from Day 8:
- FEATURE_COLS grows from 11 to 13 (two new features).
- heavy_minutes threshold lowered from 35 to 34 to match updated data.
- age_over_33: binary flag; veteran players (34+) have documented
  steeper fatigue curves.
- tired_and_away: interaction term capturing the compounding effect of
  fatigue signal combined with the documented road-game performance dip.
  XGBoost can find this conjunction via splitting, but an explicit feature
  lets shallower trees find it on the first split.

Retraining required if FEATURE_COLS is changed. The model artifact
(risk_model.pkl) expects columns in exactly this order.
"""
import pandas as pd

POSITION_MAP: dict = {"PG": 0, "SG": 1, "SF": 2, "PF": 3, "C": 4}

FEATURE_COLS: list = [
    # Primary fatigue signals
    "back_to_back",           # 0/1: consecutive nights
    "games_in_7d",            # int: rolling 7-day game count
    "rolling_minutes_7d",     # float: mean minutes over last 5 games
    "minutes_trend",          # float: slope of recent minutes (+ = load rising)
    "performance_volatility", # float: std dev of recent point totals
    # Player context
    "age",                    # int: older players recover slower
    "is_away",                # 0/1: road games correlate with lower output
    "position_encoded",       # int: from POSITION_MAP
    # Derived binary flags
    "high_workload",          # 0/1: games_in_7d >= 4
    "heavy_minutes",          # 0/1: rolling_minutes_7d > 34
    "age_over_33",            # 0/1: veteran fatigue flag (NEW in Day 9)
    # Interaction terms
    "b2b_high_workload",      # 0/1: B2B AND games_in_7d >= 4 (compounding)
    "tired_and_away",         # 0/1: (B2B OR high workload) AND away (NEW in Day 9)
]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform raw game log DataFrame into the model feature matrix.

    Input df must contain at minimum:
        back_to_back, games_in_7d, rolling_minutes_7d, minutes_trend,
        performance_volatility, age, is_away, position

    Returns a DataFrame with exactly FEATURE_COLS in defined order.
    NaN values are left as-is; XGBoost handles missing values natively.
    """
    feat = df.copy()

    # Encode position string to integer
    feat["position_encoded"] = (
        feat["position"].map(POSITION_MAP).fillna(2).astype(int)
    )

    # Binary flags
    feat["high_workload"] = (feat["games_in_7d"] >= 4).astype(int)
    feat["heavy_minutes"] = (feat["rolling_minutes_7d"] > 34.0).astype(int)
    feat["age_over_33"]   = (feat["age"] > 33).astype(int)

    # Interaction terms: explicit conjunctions help shallow trees
    feat["b2b_high_workload"] = (
        (feat["back_to_back"] == 1) & (feat["games_in_7d"] >= 4)
    ).astype(int)

    feat["tired_and_away"] = (
        ((feat["back_to_back"] == 1) | (feat["games_in_7d"] >= 4))
        & (feat["is_away"] == 1)
    ).astype(int)

    return feat[FEATURE_COLS].copy()


def player_stats_to_features(
    position:               str,
    age:                    int,
    back_to_back:           bool,
    games_in_7d:            int,
    rolling_minutes_7d:     float,
    minutes_trend:          float,
    performance_volatility: float,
    is_away:                bool = False,
) -> pd.DataFrame:
    """
    Convert individual player stats into a single-row feature DataFrame.

    Used by API routes (Day 9+) to get model-ready features from
    the fatigue_scores table. All derived features (age_over_33,
    tired_and_away, etc.) are computed automatically inside build_features.
    No changes to this signature are needed for the new features.
    """
    row: dict = {
        "back_to_back":           int(back_to_back),
        "games_in_7d":            int(games_in_7d),
        "rolling_minutes_7d":     float(rolling_minutes_7d),
        "minutes_trend":          float(minutes_trend),
        "performance_volatility": float(performance_volatility),
        "age":                    int(age),
        "is_away":                int(is_away),
        "position":               position,
    }
    return build_features(pd.DataFrame([row]))