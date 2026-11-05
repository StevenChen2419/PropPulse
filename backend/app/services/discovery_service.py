from typing import Optional

from app.models import Prop

DISCOVERY_WEIGHTS = {
    "l5_form": 0.20,
    "l10_form": 0.25,
    "season_form": 0.15,
    "sample_confidence": 0.15,
    "price_quality": 0.15,
    "book_coverage": 0.05,
    "line_movement": 0.05,
}


def discovery_history_summary(trends):
    """Retain only the exact historical inputs consumed by the scorer.

    Full response trends are still built by the existing serializer. A compact
    tuple lets preparation release per-game dictionaries before scoring starts.
    """
    if trends is None:
        return None
    return (trends["l5"]["hit_rate"], trends["l10"]["hits"], trends["l10"]["decisions"],
            trends["l10"]["hit_rate"], trends["season_window"]["decisions"],
            trends["season_window"]["hit_rate"])


def discovery_history_windows(summary):
    if summary is None:
        return None
    l5_rate, l10_hits, l10_decisions, l10_rate, season_decisions, season_rate = summary
    return {"l5": {"hit_rate": l5_rate},
            "l10": {"hits": l10_hits, "decisions": l10_decisions, "hit_rate": l10_rate},
            "season_window": {"decisions": season_decisions, "hit_rate": season_rate}}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _american_decimal(odds: int) -> float:
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / abs(odds) if odds < 0 else 1.0


def _format_odds(odds: int) -> str:
    return f"+{odds}" if odds > 0 else str(odds)


def score_discovery_prop(
    prop: Prop,
    trends: Optional[dict],
    best_over: Optional[dict],
    sportsbook_count: int,
) -> Optional[dict]:
    if not trends or trends["season_window"]["decisions"] < 5:
        return None

    l5 = trends["l5"]
    l10 = trends["l10"]
    season = trends["season_window"]
    l5_rate = l5["hit_rate"] or 0.0
    l10_rate = l10["hit_rate"] or 0.0
    season_rate = season["hit_rate"] or 0.0

    price_score = 0.0
    if best_over:
        # -200 maps to 0, +150 maps to 1, with common -110 prices near 0.4.
        price_score = _clamp((_american_decimal(best_over["odds"]) - 1.5) / 1.0)

    if prop.line_24h_ago is None:
        movement_score = 0.5
    else:
        movement = prop.line - prop.line_24h_ago
        movement_score = 1.0 if movement < -0.001 else 0.0 if movement > 0.001 else 0.5

    components = {
        "l5_form": l5_rate,
        "l10_form": l10_rate,
        "season_form": season_rate,
        "sample_confidence": _clamp(season["decisions"] / 20.0),
        "price_quality": price_score,
        "book_coverage": _clamp(sportsbook_count / 5.0),
        "line_movement": movement_score,
    }
    score = round(
        100 * sum(DISCOVERY_WEIGHTS[key] * value for key, value in components.items()),
        1,
    )

    reasons = [
        f"{l10['hits']}/{l10['decisions']} over {prop.line:g} in recent games",
    ]
    if best_over:
        reasons.append(
            f"Best Over {_format_odds(best_over['odds'])} at {best_over['sportsbook']}"
        )
    if season["decisions"] >= 10:
        reasons.append(
            f"{round(season_rate * 100)}% over {prop.line:g} this season"
        )
    elif sportsbook_count > 1:
        reasons.append(f"Available at {sportsbook_count} sportsbooks")

    return {
        "score": score,
        "reasons": reasons[:3],
        "components": {key: round(value, 3) for key, value in components.items()},
    }
