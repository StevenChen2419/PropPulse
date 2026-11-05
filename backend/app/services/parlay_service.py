"""Illustrative market-price copula estimates, not sportsbook SGP quotes."""
from collections import defaultdict
from datetime import datetime, timezone
import math

import numpy as np
from scipy.stats import norm, rankdata, qmc

from app.models import PlayerGameLog, Prop
from app.services.offer_service import offer_availability

REAL_SOURCES = {"MLB": "mlb_stats_api", "WNBA": "espn_wnba"}
SAMPLES = 32768


def naive_utc(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def historical_rho(left, right, logs):
    cutoff = min(naive_utc(left.game_time), naive_utc(right.game_time), datetime.now(timezone.utc).replace(tzinfo=None))
    start = datetime(cutoff.year - 1, 1, 1)

    def values(prop):
        result = {}
        for log in logs.get(prop.player_id, []):
            if (log.sport != prop.player.sport or log.source != REAL_SOURCES.get(log.sport)
                    or not log.external_game_id or not start <= naive_utc(log.game_date) < cutoff):
                continue
            stats = log.stats or {}
            value = stats.get(prop.prop_type)
            if value is None and prop.prop_type == "pra" and all(
                isinstance(stats.get(k), (int, float)) and not isinstance(stats[k], bool)
                and math.isfinite(stats[k]) for k in ("points", "rebounds", "assists")
            ):
                value = sum(stats[k] for k in ("points", "rebounds", "assists"))
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                result[(log.source, log.sport, log.external_game_id)] = value
        return result

    a, b = values(left), values(right)
    shared = sorted(a.keys() & b.keys())
    n = len(shared)
    if n < 20:
        return None, n
    x, y = np.array([a[k] for k in shared]), np.array([b[k] for k in shared])
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        return None, n
    x, y = (norm.ppf((rankdata(v) - 0.5) / n) for v in (x, y))
    return float(np.corrcoef(x, y)[0, 1]) * n / (n + 30), n


def joint_probability(probabilities, correlations):
    """Deterministic Sobol integration with exact independent baseline."""
    n = len(probabilities)
    if np.allclose(correlations, np.eye(n)):
        return float(np.prod(probabilities))
    eigenvalues, vectors = np.linalg.eigh(correlations)
    repaired = (vectors * np.maximum(eigenvalues, 1e-8)) @ vectors.T
    scales = np.sqrt(np.diag(repaired))
    repaired /= np.outer(scales, scales)
    normals = norm.ppf(qmc.Sobol(d=n, scramble=True, seed=2026).random_base2(15))
    draws = normals @ np.linalg.cholesky(repaired).T
    hits = int(np.all(draws <= norm.ppf(probabilities), axis=1).sum())
    if hits < 32:
        return None
    return min((hits + 0.5) / (SAMPLES + 1), min(probabilities))


def estimate_parlay(db, items, assumed_correlation=0.15):
    result = {"decimal": None, "american": None, "independent_decimal": None,
              "method": "unavailable", "historical_pairs": 0, "assumed_pairs": 0,
              "min_shared_games": None, "warnings": [], "reason": None}

    def reject(reason):
        result["reason"] = reason
        return result

    if not 2 <= len(items) <= 12 or not math.isfinite(assumed_correlation) or not 0 <= assumed_correlation <= 0.6:
        return reject("Use 2–12 picks and an assumed correlation from 0 to 0.6.")
    if len({item.sportsbook for item in items}) != 1:
        return reject("Choose one sportsbook for all picks.")
    props = {str(prop.id): prop for prop in db.query(Prop).filter(Prop.id.in_([item.prop_id for item in items])).all()}
    selected, probabilities, seen = [], [], set()
    now = datetime.now(timezone.utc)
    for item in items:
        prop = props.get(item.prop_id)
        if prop is None or not prop.is_active:
            return reject("A selected prop is unavailable.")
        event = prop.odds_event_id
        if not event or event.lower().startswith(("mock", "synthetic")) or not prop.game_time:
            return reject("Reliable game identity is missing for a pick.")
        key = (event, prop.player_id, prop.prop_type)
        if key in seen:
            return reject("Repeated picks for the same player statistic can be redundant or contradictory; remove one.")
        components = {"points", "rebounds", "assists"}
        if any(prior.odds_event_id == event and prior.player_id == prop.player_id
               and ((prop.prop_type == "pra" and prior.prop_type in components)
                    or (prior.prop_type == "pra" and prop.prop_type in components))
               for prior in selected):
            return reject("PRA overlaps this player's points, rebounds or assists pick; remove one to estimate this combination.")
        seen.add(key)
        decision = offer_availability(prop, item.sportsbook, item.line, item.side, now)
        if not decision["actionable"]:
            result["availability"] = decision["availability"]
            return reject("A selected sportsbook offer is unavailable: " + decision["availability"] + ".")
        odds = decision["odds"]
        decimal = 1 + (odds / 100 if odds > 0 else 100 / -odds)
        probabilities.append(1 / decimal)
        selected.append(prop)
    result["independent_decimal"] = float(1 / np.prod(probabilities))
    if any(p < 0.01 or p > 0.99 for p in probabilities):
        return reject("A leg has extreme odds beyond this estimator's supported range.")
    logs = defaultdict(list)
    for log in db.query(PlayerGameLog).filter(PlayerGameLog.player_id.in_([p.player_id for p in selected])).all():
        logs[log.player_id].append(log)
    groups = defaultdict(list)
    for i, prop in enumerate(selected):
        groups[(prop.player.sport, prop.odds_event_id)].append(i)
    joint = 1.0
    shared_counts = []
    for indices in groups.values():
        matrix = np.eye(len(indices))
        for i, li in enumerate(indices):
            for j in range(i):
                ri = indices[j]
                rho, shared = historical_rho(selected[li], selected[ri], logs)
                if rho is None:
                    rho = assumed_correlation
                    result["assumed_pairs"] += 1
                else:
                    result["historical_pairs"] += 1
                    shared_counts.append(shared)
                if items[li].side != items[ri].side:
                    rho = -rho
                matrix[i, j] = matrix[j, i] = rho
        block = joint_probability([probabilities[i] for i in indices], matrix)
        if block is None:
            return reject("Joint probability is too small for a stable estimate; reduce the number of picks.")
        joint *= block
    decimal = 1 / joint
    result.update(decimal=float(decimal), american=float(100 * (decimal - 1) if decimal >= 2 else -100 / (decimal - 1)),
                  method="mixed" if result["historical_pairs"] and result["assumed_pairs"] else
                  "historical" if result["historical_pairs"] else "assumed" if result["assumed_pairs"] else "independent",
                  min_shared_games=min(shared_counts) if shared_counts else None)
    result["warnings"].append("Illustrative price estimate using market-implied probabilities that include bookmaker margin; not a fair-probability model or sportsbook quote.")
    if result["assumed_pairs"]:
        result["warnings"].append("Missing or insufficient shared history uses your uncalibrated correlation assumption; it is not empirical evidence.")
    if result["historical_pairs"]:
        result["warnings"].append("Historical rank correlations are shrunk toward zero and may not describe this matchup; discrete statistics and pushes are approximated.")
    return result
