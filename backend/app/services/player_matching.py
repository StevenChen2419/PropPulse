"""Exact, candidate-aware matching and bounded diagnostics; never fuzzy-match names."""
from collections import Counter
from dataclasses import dataclass

from app.services.team_directory import normalize_player_name


def candidate_index(items, name=lambda item: item.name):
    result = {}
    for item in items:
        result.setdefault(normalize_player_name(name(item)), []).append(item)
    return result


def roster_candidates(directory, normalized_name):
    value = directory.get(normalized_name)
    return value if isinstance(value, list) else [value] if value else []


def known_team(team):
    return normalize_player_name(team) not in {"", "unk", "unknown"}


def team_in_event(team, item):
    return known_team(team) and any(
        normalize_player_name(team) == normalize_player_name(value or "")
        for value in (item.get("home_team"), item.get("away_team"))
    )


@dataclass
class MatchResult:
    reason: str
    candidate_count: int | None
    roster_candidate_count: int | None
    roster_status: str
    player: object = None
    roster: dict = None

    @property
    def matched(self):
        return self.reason == "matched"


def match_odds_player(item, local_candidates, directory, *, roster_status="unavailable", smoke=False):
    candidates = local_candidates.get(normalize_player_name(item.get("player_name", "")), [])
    roster = roster_candidates(directory, normalize_player_name(item.get("player_name", "")))
    status = "not_requested_smoke" if smoke else roster_status
    def result(reason, player=None, team=None):
        return MatchResult(reason, len(candidates), len(roster), status, player, team)
    if len(candidates) > 1:
        return result("ambiguous_player")
    if len(roster) > 1:
        return result("roster_name_collision")
    player = candidates[0] if candidates else None
    if smoke:
        if player is None:
            return result("scope_existing_players_only")
        if not known_team(player.team):
            return result("unknown_team")
        return result("matched" if team_in_event(player.team, item) else "team_not_in_event", player)
    team = roster[0] if roster else None
    if team:
        if not known_team(team.get("team")):
            return result("unknown_team")
        if not team_in_event(team["team"], item):
            return result("team_not_in_event")
        return result("matched", player, team)
    if player is None:
        return result("roster_unavailable" if status == "unavailable" else "missing_player")
    if not known_team(player.team):
        return result("unknown_team")
    return result("matched" if team_in_event(player.team, item) else "team_not_in_event", player)


class MatchingDiagnostics:
    """Counts cover every row; only samples are capped. Groups count once per reason.

    A group may have accepted and rejected books, so group counts are not additive
    across reasons. Row counts are mutually exclusive final row dispositions.
    """
    def __init__(self, sport, *, smoke=False, sample_limit=40, row_unit="offer_rows"):
        self.sport, self.smoke = sport, smoke
        self.sample_limit, self.row_unit = sample_limit, row_unit
        self.groups, self.rows, self.samples = Counter(), Counter(), []
        self._seen = set()
        self._sample_indices = {}
        self._sample_keys = []
        self.sample_total = 0

    def record(self, item, reason, rows=1, match=None):
        name = normalize_player_name(item.get("player_name", ""))
        key = (item.get("event_id"), item.get("prop_type"), name, reason)
        self.rows[reason] += rows
        if key in self._seen:
            index = self._sample_indices.get(key)
            if index is not None:
                self.samples[index]["affected_rows"] += rows
            return
        self._seen.add(key)
        self.groups[reason] += 1
        self.sample_total += 1
        sample = {"sport": self.sport, "event_id": str(item.get("event_id") or "")[:128],
                "market": str(item.get("prop_type") or "")[:80], "normalized_name": name[:120],
                "outcome": "matched" if reason == "matched" else "skipped", "reason": reason,
                "candidate_count": match.candidate_count if match else None,
                "roster_candidate_count": match.roster_candidate_count if match else None,
                "roster_status": match.roster_status if match else "not_evaluated",
                "smoke_existing_players_only": self.smoke, "affected_rows": rows}
        if len(self.samples) < self.sample_limit:
            self._sample_indices[key] = len(self.samples)
            self._sample_keys.append(key)
            self.samples.append(sample)
        elif reason != "matched":
            # Keep later failures visible even after a long prefix of matches.
            index = next((i for i, value in enumerate(self.samples) if value["outcome"] == "matched"), None)
            if index is not None:
                self._sample_indices.pop(self._sample_keys[index])
                self._sample_keys[index] = key
                self._sample_indices[key] = index
                self.samples[index] = sample

    def report(self):
        return {"stage": "persistence" if self.row_unit == "offer_rows" else "history_identity",
                "matched_semantics": "accepted_for_reconciliation_not_committed" if self.row_unit == "offer_rows" else "unique_provider_identity_not_log_write",
                "transaction_outcome": "pending" if self.row_unit == "offer_rows" else "not_applicable",
                "row_unit": self.row_unit, "group_count_semantics": "unique_event_market_name_per_reason",
                "group_counts": dict(self.groups), "row_counts": dict(self.rows),
                "sample_limit": self.sample_limit, "sampling_policy": "skips_before_matches", "samples": self.samples,
                "samples_truncated": max(0, self.sample_total - len(self.samples))}
