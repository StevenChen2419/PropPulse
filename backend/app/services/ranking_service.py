from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from app.models import Prop, User, Interaction, FatigueScore, Player
from app.services.fatigue_service import fatigue_to_dict


WEIGHTS = {
    "user_affinity":      0.30,
    "player_affinity":    0.20,
    "prop_type_affinity": 0.15,
    "popularity":         0.15,
    "line_movement":      0.10,
    "fatigue_edge":       0.10,
}


def _normalize(value: float, min_v: float = 0.0, max_v: float = 1.0) -> float:
    if max_v == min_v:
        return 0.0
    return max(0.0, min(1.0, (value - min_v) / (max_v - min_v)))


def _user_affinity(
    user: Optional[User],
    prop: Prop,
    interactions: List[Interaction],
    affinities=None,
) -> float:
    if not user:
        return 0.0
    score = 0.0
    if affinities is None:
        interacted_sports = set()
        interacted_types = set()
        for ia in interactions:
            if ia.prop and ia.prop.player:
                interacted_sports.add(ia.prop.player.sport)
            if ia.prop:
                interacted_types.add(ia.prop.prop_type)
    else:
        interacted_sports, interacted_types = affinities
    if prop.player.sport in (user.fav_sports or []):
        score += 0.5
    if prop.player.sport in interacted_sports:
        score += 0.3
    if prop.prop_type in interacted_types:
        score += 0.2
    return min(1.0, score)


def _player_affinity(
    user: Optional[User],
    prop: Prop,
    interactions: List[Interaction],
    interacted_player_ids=None,
) -> float:
    if not user:
        return 0.0
    if interacted_player_ids is None:
        interacted_player_ids = {ia.prop.player_id for ia in interactions if ia.prop}
    score = 0.0
    if str(prop.player_id) in (user.fav_players or []):
        score += 0.7
    if prop.player_id in interacted_player_ids:
        score += 0.3
    return min(1.0, score)


def _prop_type_affinity(user: Optional[User], prop: Prop) -> float:
    if not user or not user.fav_prop_types:
        return 0.3  # neutral default for users without preferences
    return 1.0 if prop.prop_type in user.fav_prop_types else 0.1


def _popularity(prop: Prop, max_popularity: int) -> float:
    return _normalize(prop.popularity_count, 0, max(max_popularity, 1))


def _line_movement_score(prop: Prop) -> float:
    if not prop.line_24h_ago or prop.line_24h_ago == 0:
        return 0.0
    movement = abs(prop.line - prop.line_24h_ago) / max(abs(prop.line_24h_ago), 0.5)
    return min(1.0, movement * 5)  # a 20% move scores 1.0


def _fatigue_edge_score(fs: Optional[FatigueScore]) -> float:
    if not fs:
        return 0.0
    return fs.fatigue_score


def build_reasons(
    user: Optional[User],
    prop: Prop,
    scores: dict,
    fs: Optional[FatigueScore],
) -> List[str]:
    """
    Return up to 3 plain-English reasons why this prop was surfaced.

    Priority order:
    1. Sport affinity   -- personalization signal, strongest
    2. Player affinity  -- user tracks this player specifically
    3. Prop type pref   -- user prefers this prop category
    4. Fatigue / risk   -- our ML differentiator, always shown when present
    5. Line movement    -- market signal
    6. Popularity       -- fallback for cold-start and low-signal props

    Rules:
    - Max 3 reasons.
    - Never expose score values or internal field names.
    - Fatigue reasons use exact text from shap_reasons when available.
    - Popularity is shown as a second reason only when another reason exists,
      or as the sole reason when no personalization signal is present.
    """
    reasons: List[str] = []

    # 1. Sport affinity
    if user and prop.player.sport in (user.fav_sports or []):
        reasons.append(f"You follow {prop.player.sport}")

    # 2. Player affinity
    if len(reasons) < 3:
        if scores["player_affinity"] >= 0.7:
            reasons.append(f"You track {prop.player.name}")
        elif scores["player_affinity"] >= 0.3:
            reasons.append(f"Based on your {prop.player.sport} history")

    # 3. Prop type preference
    if len(reasons) < 3:
        if scores["prop_type_affinity"] >= 1.0:
            reasons.append(f"You prefer {prop.prop_type} props")

    # 4. Fatigue / risk signal
    # Use the human-readable shap_reasons from the model when available.
    # Fall back to generic flag descriptions if not.
    if len(reasons) < 3 and fs:
        shap = fs.shap_reasons or []
        flags = fs.risk_flags or []

        # Try shap_reasons first (most descriptive)
        fatigue_added = False
        for reason_text in shap[:2]:  # at most one fatigue reason
            if len(reasons) < 3 and reason_text not in reasons:
                reasons.append(reason_text)
                fatigue_added = True
                break

        # Fall back to flag-based labels if shap_reasons was empty
        if not fatigue_added and len(reasons) < 3:
            if "back-to-back" in flags:
                reasons.append("Back-to-back game tonight")
            elif "heavy-workload" in flags:
                reasons.append("Heavy recent workload")
            elif "high-minutes" in flags:
                reasons.append("High minutes load this week")

    # 5. Line movement
    if len(reasons) < 3 and prop.line_24h_ago is not None:
        diff = prop.line - prop.line_24h_ago
        if diff >= 0.5:
            reasons.append("Line moved up in last 24h")
        elif diff <= -0.5:
            reasons.append("Line moved down in last 24h")

    # 6. Popularity fallback
    # Show as the only reason for cold-start users, or as a second reason
    # when popularity is genuinely high and we have room.
    if len(reasons) == 0:
        reasons.append("Trending among users")
    elif len(reasons) < 3 and scores["popularity"] >= 0.65:
        reasons.append("Trending among users")

    return reasons[:3]


def rank_props(
    props: List[Prop],
    user: Optional[User],
    db: Session,
) -> List[dict]:
    user_interactions: List[Interaction] = []
    if user:
        user_interactions = (
            db.query(Interaction)
            .options(joinedload(Interaction.prop).joinedload(Prop.player))
            .filter(Interaction.user_id == user.id)
            .join(Prop,   Interaction.prop_id  == Prop.id)
            .join(Player, Prop.player_id        == Player.id)
            .all()
        )

    # Candidate subjects intentionally do not populate the ORM identity map.
    # Eager interaction associations avoid per-interaction lazy reads; affinity
    # sets are identical for every candidate and need only one traversal.
    sports, types, interacted_players = set(), set(), set()
    for interaction in user_interactions:
        if interaction.prop:
            types.add(interaction.prop.prop_type)
            interacted_players.add(interaction.prop.player_id)
            if interaction.prop.player:
                sports.add(interaction.prop.player.sport)

    max_popularity = max((p.popularity_count for p in props), default=1)

    # fatigue_scores.player_id is unique. Fetch once for the candidate players
    # instead of issuing one identical lookup for every market/Event prop.
    player_ids = {prop.player_id for prop in props}
    fatigue_by_player = {score.player_id: score for score in (
        db.query(FatigueScore).filter(FatigueScore.player_id.in_(player_ids)).all()
        if player_ids else []
    )}
    fatigue_output = {player_id: fatigue_to_dict(score) for player_id, score in fatigue_by_player.items()}

    ranked = []
    for prop in props:
        fs = fatigue_by_player.get(prop.player_id)

        scores = {
            "user_affinity":      _user_affinity(user, prop, user_interactions, (sports, types)),
            "player_affinity":    _player_affinity(user, prop, user_interactions, interacted_players),
            "prop_type_affinity": _prop_type_affinity(user, prop),
            "popularity":         _popularity(prop, max_popularity),
            "line_movement":      _line_movement_score(prop),
            "fatigue_edge":       _fatigue_edge_score(fs),
        }

        final_score = sum(WEIGHTS[k] * v for k, v in scores.items())
        reasons     = build_reasons(user, prop, scores, fs)
        line_diff   = round(prop.line - (prop.line_24h_ago or prop.line), 2)

        ranked.append({
            "prop":         prop,
            "fatigue":      fatigue_output.get(prop.player_id),
            "rank_score":   round(final_score, 4),
            "reasons":      reasons,
            "scores":       scores,
            "line_movement": line_diff,
        })

    ranked.sort(key=lambda x: x["rank_score"], reverse=True)
    return ranked
