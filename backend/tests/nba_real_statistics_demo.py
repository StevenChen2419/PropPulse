"""Opt-in Phase 5D disposable loader. No transport; raw artifacts stay ignored.

The owner of the disposable database supplies actual, separately authorized NBA
responses and owns commit/rollback. Events are diagnostic reference fixtures,
never real scheduled games or sportsbook-backed offers.
"""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re

from nba_api.stats.static import players, teams
from sqlalchemy import null

from app.models import Event, Player, Prop
from app.services.nba_api_provider import normalize_player_statistics, normalize_team_games, verified_crosswalk
from app.services.nba_evidence_service import _test_target, append_normalized_evidence
from app.services.nba_statistics_service import import_player_statistics
from nba_real_rest_demo import _same

UTC = timezone.utc
SEASON = "2025-26"
COMPETITION = "Regular Season"
IDENTITIES = (
    ("2544", "LeBron James", "5d000000-0000-4000-8000-000000000001"),
    ("1627759", "Jaylen Brown", "5d000000-0000-4000-8000-000000000002"),
    ("203999", "Nikola Jokić", "5d000000-0000-4000-8000-000000000003"),
)


def _observed(value):
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if observed.tzinfo is None or observed > datetime.now(UTC):
        raise ValueError("Actual aware observation timestamp required; future observations forbidden")
    return observed.astimezone(UTC)


def _rows(payload):
    tables = [table for table in payload["resultSets"] if table["name"] == "PlayerGameLog"]
    if len(tables) != 1:
        raise ValueError("One original PlayerGameLog table required")
    return [dict(zip(tables[0]["headers"], row, strict=True)) for row in tables[0]["rowSet"]]


def _raw_number(value, minutes=False):
    """Independent source oracle; does not call production parsers/calculators."""
    if isinstance(value, bool) or value is None:
        return None
    if minutes and isinstance(value, str) and ":" in value:
        if not re.fullmatch(r"\d+:[0-5]\d(?:\.\d+)?", value):
            return None
        first, second = value.split(":")
        value = float(first) + float(second) / 60
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or (minutes and number > 100):
        return None
    return number if minutes or number.is_integer() else None


def source_oracle(payload):
    """Compute appearance windows directly from raw returned statistics."""
    by_game = {}
    for row in _rows(payload):
        raw_date = row["GAME_DATE"]
        # NBA responses supported by the importer include an ISO datetime-shaped
        # date. It still denotes an Eastern calendar date, never an actual tipoff.
        for date_format in ("%b %d, %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                day = datetime.strptime(raw_date, date_format).date()
                break
            except ValueError:
                continue
        else:
            raise ValueError("Unsupported source game date")
        metrics = {key: _raw_number(row.get(field), key == "minutes") for key, field in
                   (("points", "PTS"), ("rebounds", "REB"), ("assists", "AST"), ("minutes", "MIN"))}
        appearance = any((_raw_number(row.get(field), field == "MIN") or 0) > 0
                         for field in ("PTS", "REB", "AST", "MIN", "STL", "BLK", "FG3M"))
        if appearance:
            by_game[row["Game_ID"]] = dict(game_id=row["Game_ID"], game_date=day.isoformat(), **metrics)
    eligible = sorted(by_game.values(), key=lambda row: (row["game_date"], row["game_id"]), reverse=True)
    result = dict(recorded_appearances=len(eligible), latest_appearance=eligible[0]["game_date"] if eligible else None,
                  coverage_start=eligible[-1]["game_date"] if eligible else None,
                  coverage_end=eligible[0]["game_date"] if eligible else None)
    for count in (5, 10):
        sample = eligible[:count]
        window = dict(appearances=len(sample), game_ids=[row["game_id"] for row in sample],
                      game_dates=[row["game_date"] for row in sample], samples=sample)
        for metric in ("points", "rebounds", "assists", "minutes"):
            values = [row[metric] for row in sample if row[metric] is not None]
            window[metric] = dict(average=round(sum(values) / len(values), 2) if values else None,
                                  valid_samples=len(values))
        result[f"l{count}"] = window
    return result


def load_artifact(path):
    artifact_path = Path(path).resolve(strict=True)
    if not artifact_path.is_file() or artifact_path.stat().st_size > 4_000_000:
        raise ValueError("Bounded explicit NBA response artifact required")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    if (artifact.get("actual_source") is not True or artifact.get("season") != SEASON
            or artifact.get("competition") != COMPETITION):
        raise ValueError("Actual 2025-26 Regular Season artifact required")
    requests = artifact.get("requests")
    if not isinstance(requests, list) or not 1 <= len(requests) <= 4:
        raise ValueError("One to four actual request outcomes required")
    observations = artifact.get("players")
    if not isinstance(observations, list) or not 1 <= len(observations) <= len(IDENTITIES):
        raise ValueError("One to three reviewed player responses required")
    accepted, seen = [], set()
    for item in observations:
        nba = str(item["nba_player_id"])
        identity = next((entry for entry in IDENTITIES if entry[0] == nba), None)
        if identity is None or nba in seen:
            raise ValueError("Unknown or repeated reviewed NBA identity")
        static = players.find_player_by_id(int(nba))
        if static is None or static["full_name"] != identity[1]:
            raise ValueError("Reviewed static NBA directory identity conflict")
        seen.add(nba)
        crosswalk = verified_crosswalk([dict(nba_player_id=nba, player_id=identity[2], verified=True,
            provenance=f"Phase 5D reviewed NBA static person ID {nba} -> dedicated disposable UUID {identity[2]}")])
        observed = _observed(item["observed_at"])
        normalized = normalize_player_statistics(item["payload"], observed_at=observed, crosswalk=crosswalk,
            season=SEASON, competition=COMPETITION)
        if not normalized:
            raise ValueError("Successful player response has no statistics; do not claim collection success")
        accepted.append(dict(identity=identity, crosswalk=crosswalk, observed=observed,
            payload=item["payload"], normalized=normalized, oracle=source_oracle(item["payload"])))
    return artifact, accepted


def seed_real_statistics_demo(db, path):
    _test_target(db)  # Before artifact I/O and application SQL.
    if db.new or db.dirty or db.deleted:
        raise ValueError("Dedicated loader requires a clean session")
    artifact, observations = load_artifact(path)
    directory = {str(team["id"]): team for team in teams.get_teams()}
    reference = max(item["observed"] for item in observations) + timedelta(minutes=1)
    manifests = []
    with db.begin_nested():
        for item in observations:
            nba, name, local = item["identity"]
            latest = max(item["normalized"], key=lambda row: row["game_date"])
            meta = latest["stats"]["_nba"]
            team, opponent = directory[meta["team_id"]], directory[meta["opponent_id"]]
            player_values = dict(name=name, team="Historical research fixture; current team unverified",
                                 team_abbr="FIX", sport="NBA")
            player = db.get(Player, local)
            if player is None:
                db.add(Player(id=local, **player_values))
            else:
                _same(player, player_values)
            suffix = local[-12:]
            event_id, prop_id = f"5d000010-0000-4000-8000-{suffix}", f"5d000020-0000-4000-8000-{suffix}"
            event_values = dict(provider="synthetic_fixture_5d_reference", provider_event_id=f"reference-{nba}",
                sport_key="basketball_nba", home_team=team["full_name"], away_team=opponent["full_name"],
                scheduled_start_at=reference.replace(tzinfo=None))
            event = db.get(Event, event_id)
            if event is None:
                db.add(Event(id=event_id, **event_values))
            else:
                _same(event, event_values)
            db.flush()
            prop_values = dict(player_id=local, event_id=event_id, prop_type="points", line=0.0,
                sportsbook="Historical research reference; no sportsbook line or offer", over_odds=None,
                under_odds=None, is_active=False, game_time=reference.replace(tzinfo=None),
                opponent=opponent["full_name"], is_home=True)
            prop = db.get(Prop, prop_id)
            if prop is None:
                db.add(Prop(id=prop_id, **{**prop_values, "over_odds": null(), "under_odds": null()}))
            else:
                _same(prop, prop_values)
            db.flush()
            arguments = dict(observed_at=item["observed"], crosswalk=item["crosswalk"], season=SEASON,
                             competition=COMPETITION)
            imported = import_player_statistics(db, item["payload"], **arguments)
            replay = import_player_statistics(db, item["payload"], **arguments)
            if replay["unchanged"] != len(item["normalized"]):
                raise ValueError("Statistics replay was not idempotent")
            manifests.append(dict(player_id=local, nba_player_id=nba, name=name, event_id=event_id,
                prop_id=prop_id, season=SEASON, competition=COMPETITION, actual_source=True,
                reference_at=reference.isoformat(), observed_at=item["observed"].isoformat(),
                label="Historical 2025-26 statistics; synthetic nonactionable reference Event",
                oracle=item["oracle"], imported=imported, replay=replay))
        team_item = artifact.get("team")
        if team_item is not None:
            normalized = normalize_team_games(team_item["payload"], observed_at=_observed(team_item["observed_at"]))
            if any(not row["identity"].startswith("00225") for row in normalized["records"] if row["kind"] == "game"):
                raise ValueError("Team games conflict with the reviewed 2025-26 Regular Season scope")
            # Bounded append scope; no completeness assertion and no participation rebuild.
            latest_date = max(row["game_date"] for item in observations for row in item["normalized"]).date()
            start = latest_date - timedelta(days=13)
            identities = {row["stats"]["_nba"][key] for item in observations
                          for row in [max(item["normalized"], key=lambda r: r["game_date"])]
                          for key in ("team_id", "opponent_id")}
            games = [row for row in normalized["records"] if row["kind"] == "game"
                     and {row["payload"]["home_team_id"], row["payload"]["away_team_id"]} <= identities
                     and start.isoformat() <= row["payload"]["game_at"][:10] <= latest_date.isoformat()]
            team_records = [row for row in normalized["records"] if row["kind"] == "team" and row["identity"] in identities]
            if games:
                records = team_records + games
                scope = dict(provider="nba_com", crosswalk=observations[0]["crosswalk"], sport="NBA",
                    start_date=start.isoformat(), end_date=latest_date.isoformat(), team_ids=sorted(identities), now=datetime.now(UTC))
                dry = append_normalized_evidence(db, records, **scope)
                appended = append_normalized_evidence(db, records, **scope, write=True, expected_digest=dry["digest"])
            else:
                appended = None
            for manifest in manifests:
                manifest["team_evidence"] = dict(append=appended, normalized_games=len(games),
                    issues=normalized["issues"], schedule_complete=False, partial=True)
    return manifests
