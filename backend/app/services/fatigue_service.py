from app.models import FatigueScore, Player

def fatigue_label(score: float) -> str:
    if score < 0.35:  return "Low"
    if score < 0.55:  return "Medium"
    if score < 0.75:  return "High"
    return "Critical"

def fatigue_to_dict(fs: FatigueScore) -> dict:
    if not fs:
        return None
    return {
        "fatigue_score": round(fs.fatigue_score, 3),
        "workload_score": round(fs.workload_score, 3),
        "back_to_back": fs.back_to_back,
        "games_in_7d": fs.games_in_7d,
        "rolling_minutes_7d": round(fs.rolling_minutes_7d, 1),
        "minutes_trend": round(fs.minutes_trend, 3),
        "performance_volatility": round(fs.performance_volatility, 3),
        "risk_flags": fs.risk_flags or [],
        "shap_reasons": fs.shap_reasons or [],
        "fatigue_label": fatigue_label(fs.fatigue_score),
    }

def compute_heuristic_fatigue(
    games_in_7d: int,
    back_to_back: bool,
    rolling_minutes: float,
    minutes_trend: float,
    volatility: float,
    age: int = 28,
) -> dict:
    """
    Compute fatigue score from heuristics. Used by nightly job or for
    players not yet in DB. Returns same shape as FatigueScore model.
    """
    score = 0.0
    flags = []
    reasons = []

    # Back-to-back is the strongest single signal
    if back_to_back:
        score += 0.30
        flags.append("back-to-back")
        reasons.append("Back-to-back game tonight")

    # Games density
    if games_in_7d >= 5:
        score += 0.25
        flags.append("heavy-workload")
        reasons.append(f"Heavy workload: {games_in_7d} games in 7 days")
    elif games_in_7d == 4:
        score += 0.15
        flags.append("busy-week")
        reasons.append(f"Busy week: {games_in_7d} games in 7 days")

    # Minutes load
    if rolling_minutes > 36:
        score += 0.20
        flags.append("high-minutes")
        reasons.append(f"High minutes: {rolling_minutes:.1f} avg last 7 days")
    elif rolling_minutes > 33:
        score += 0.10

    # Minutes trending up
    if minutes_trend > 0.15:
        score += 0.10
        flags.append("minutes-trending-up")
        reasons.append("Minutes trending up this week")

    # Performance volatility
    if volatility > 0.35:
        score += 0.15
        flags.append("high-volatility")
        reasons.append("High recent performance volatility")

    # Age penalty (soft)
    if age >= 35:
        score += 0.05
        reasons.append(f"Age factor ({age} years old)")

    score = min(1.0, round(score, 3))
    workload = min(1.0, round(games_in_7d / 5.0, 3))

    return {
        "fatigue_score": score,
        "workload_score": workload,
        "back_to_back": back_to_back,
        "games_in_7d": games_in_7d,
        "rolling_minutes_7d": rolling_minutes,
        "minutes_trend": minutes_trend,
        "performance_volatility": volatility,
        "risk_flags": flags,
        "shap_reasons": reasons,
        "fatigue_label": fatigue_label(score),
    }