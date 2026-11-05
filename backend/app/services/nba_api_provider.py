"""Offline NBA.com adapter. No transport, settings, DB or application lifespan.

The explicit probe uses nba_api; these functions consume its JSON dictionaries.
There is deliberately no live fetch in player research and no automatic mapping
from ESPN IDs, names, current teams, or odds Events.
"""
from collections import defaultdict
from collections.abc import Mapping
from types import MappingProxyType
from datetime import date, datetime, time, timezone
import math
import re
from uuid import UUID
from zoneinfo import ZoneInfo

from nba_api.stats.static import teams

UTC = timezone.utc
EASTERN = ZoneInfo("America/New_York")


def nba_id(value, *, game=False):
    if type(value) not in (str, int) or not re.fullmatch(r"[0-9]{1,10}", str(value)) or int(value) <= 0:
        raise ValueError("Invalid NBA identity")
    result = str(int(value))
    return result.zfill(10) if game else result


class ReviewedPlayerCrosswalk(Mapping):
    """Immutable reviewed IDs and their per-association review provenance."""
    def __init__(self, identities, provenance):
        if set(identities) != set(provenance) or any(
                not isinstance(note, str) or not note.strip() for note in provenance.values()):
            raise ValueError("Every reviewed player association requires provenance")
        self._identities = MappingProxyType(dict(identities))
        self.provenance = MappingProxyType(dict(provenance))

    def __getitem__(self, key):
        return self._identities[key]

    def __iter__(self):
        return iter(self._identities)

    def __len__(self):
        return len(self._identities)


def verified_crosswalk(entries):
    """Explicit reviewed assertions only; immutable provenance accompanies IDs.

    A public NBA identity alone cannot identify an existing local UUID. The
    reviewer must independently establish that association before supplying it.
    Conflicting or many-to-one mappings fail closed, including duplicate keys.
    """
    result, provenance = {}, {}
    for entry in entries:
        if entry.get("verified") is not True or not isinstance(entry.get("provenance"), str) or not entry["provenance"].strip():
            raise ValueError("A reviewed identity crosswalk with provenance is required")
        athlete, local = nba_id(entry["nba_player_id"]), str(UUID(str(entry["player_id"])))
        if athlete in result or local in result.values():
            raise ValueError("Ambiguous player crosswalk")
        result[athlete] = local
        provenance[athlete] = entry["provenance"].strip()
    return ReviewedPlayerCrosswalk(result, provenance)


def _observed(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Explicit timezone-aware observation time required")
    return value.astimezone(UTC)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _date(value):
    if not isinstance(value, str):
        raise ValueError("Missing NBA game date")
    for fmt in ("%b %d, %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError("Unsupported NBA date format")


def _rows(payload, name):
    sets = payload.get("resultSets")
    if not isinstance(sets, list):
        raise ValueError("Missing NBA result sets")
    selected = [s for s in sets if s.get("name") == name]
    if len(selected) != 1:
        raise ValueError("Ambiguous NBA result set")
    headers, rows = selected[0].get("headers"), selected[0].get("rowSet")
    if (not isinstance(headers, list) or any(not isinstance(h, str) for h in headers)
            or len(set(headers)) != len(headers) or not isinstance(rows, list) or len(rows) > 10000
            or any(not isinstance(row, list) or len(row) != len(headers) for row in rows)):
        raise ValueError("Malformed NBA result set")
    return [dict(zip(headers, row)) for row in rows]


def _record(kind, identity, payload, observed, source, **context):
    return dict(kind=kind, identity=identity, payload=payload,
                observed_at=observed.isoformat(), source=source, **context)


def normalize_team_games(payload, *, observed_at, team_ids=None):
    """Pair explicit final W/L results, never infer finality from a past date.

    LeagueGameLog has dates, not start/completion times. Midnight is a calendar
    anchor with eastern_date precision, never a fabricated actual start. A pair
    must have reciprocal home/away matches, known NBA team IDs and opposite W/L.
    This does not assert that any date interval or schedule is complete.
    """
    observed = _observed(observed_at)
    scope = {nba_id(identity) for identity in team_ids} if team_ids is not None else None
    directory = {str(t["id"]): t for t in teams.get_teams()}
    grouped = defaultdict(list)
    for row in _rows(payload, "LeagueGameLog"):
        grouped[nba_id(row.get("GAME_ID"), game=True)].append(row)
    records, issues = [], []
    source = "nba_api.stats.leaguegamelog"
    for game_id, rows in sorted(grouped.items()):
        try:
            if len(rows) != 2:
                raise ValueError("Incomplete or duplicated team result pair")
            ids = [nba_id(row["TEAM_ID"]) for row in rows]
            if scope is not None and not scope.intersection(ids):
                continue
            dates = [_date(row["GAME_DATE"]) for row in rows]
            if (len(set(ids)) != 2 or not set(ids) <= directory.keys() or dates[0] != dates[1]
                    or {row.get("WL") for row in rows} != {"W", "L"}
                    or any(not _number(row.get("PTS")) or row["PTS"] < 0 for row in rows)):
                raise ValueError("Conflicting team result identity/date/outcome")
            if rows[0]["PTS"] == rows[1]["PTS"] or any((row["WL"] == "W") != (row["PTS"] > rows[1-i]["PTS"]) for i, row in enumerate(rows)):
                raise ValueError("Conflicting final result score")
            abbr = [directory[identity]["abbreviation"] for identity in ids]
            home = [i for i, row in enumerate(rows) if row.get("MATCHUP") == f"{abbr[i]} vs. {abbr[1-i]}"]
            if len(home) != 1 or rows[1-home[0]].get("MATCHUP") != f"{abbr[1-home[0]]} @ {abbr[home[0]]}":
                raise ValueError("Unresolved team sides")
            at = datetime.combine(dates[0], time.min, EASTERN).astimezone(UTC)
            if dates[0] >= observed.astimezone(EASTERN).date():
                raise ValueError("Current/future date cannot establish date-only finality")
            for identity in ids:
                records.append(_record("team", identity, {"name": directory[identity]["full_name"]}, observed, source))
            records.append(_record("game", game_id, dict(home_team_id=ids[home[0]], away_team_id=ids[1-home[0]],
                scheduled_at=at.isoformat(), game_at=at.isoformat(), completed_at=None, status="completed",
                time_precision="eastern_date"), observed, source, game_id=game_id))
        except (ValueError, KeyError, TypeError):
            issues.append(f"Game {game_id}: unsupported/conflicting team results withheld.")
    return {"records": records, "issues": issues, "schedule_complete": False}


def normalize_player_games(payload, *, observed_at, crosswalk, game_records):
    """Recorded positive-minute appearances joined to reconciled team results.

    Missing/zero minutes do not prove an appearance or a DNP. The unvalidated
    Live contract supplies no fallback evidence. No absent row is emitted.
    """
    observed = _observed(observed_at)
    games = defaultdict(list)
    for game in game_records:
        if game["kind"] == "game":
            games[game["game_id"]].append(game)
    directory = {t["abbreviation"]: str(t["id"]) for t in teams.get_teams()}
    records, issues = [], []
    source = "nba_api.stats.playergamelog"
    for row in _rows(payload, "PlayerGameLog"):
        athlete = nba_id(row.get("Player_ID"))
        game_id = nba_id(row.get("Game_ID"), game=True)
        if athlete not in crosswalk:
            issues.append("Unknown NBA/local player crosswalk; appearance withheld.")
            continue
        matches = games[game_id]
        if not matches or any(g["payload"] != matches[0]["payload"] for g in matches):
            issues.append("Missing/conflicting completed game; appearance withheld.")
            continue
        game = matches[0]["payload"]
        matchup = row.get("MATCHUP", "")
        match = re.fullmatch(r"([A-Z]{3}) (vs\.|@) ([A-Z]{3})", matchup) if isinstance(matchup, str) else None
        team = directory.get(match[1]) if match else None
        opponent = directory.get(match[3]) if match else None
        expected = (game["home_team_id"], game["away_team_id"]) if match and match[2] == "vs." else (game["away_team_id"], game["home_team_id"])
        if (game["status"] != "completed" or (team, opponent) != expected
                or _date(row["GAME_DATE"]) != datetime.fromisoformat(game["game_at"]).astimezone(EASTERN).date()
                or not _number(row.get("MIN")) or not 0 < row["MIN"] <= 100):
            issues.append("Unresolved player game/date/team/appearance; evidence withheld.")
            continue
        local = str(UUID(crosswalk[athlete]))
        records.extend([
            _record("athlete", athlete, {}, observed, source, player_id=local),
            _record("participation", f"{game_id}-{athlete}", {"athlete_id": athlete, "state": "appeared"},
                    observed, source, player_id=local, team_id=team, game_id=game_id),
        ])
    return {"records": records, "issues": issues}


def normalize_live_boxscore(payload, *, observed_at, crosswalk):
    """Live response semantics remain unvalidated; emit no durable evidence.

    The bounded Live probe failed. Synthetic examples cannot establish the
    operational meaning of played/status/reason, finality or player omissions.
    """
    _observed(observed_at)
    return {"records": [], "issues": [
        "NBA Live BoxScore contract is unvalidated; no operational evidence is emitted."]}


def normalize_player_statistics(payload, *, observed_at, crosswalk, season,
                                competition, max_records=1000):
    """Normalize bounded Stats PlayerGameLog rows without participation inference.

    ``game_date`` is only an Eastern calendar anchor, never a start/completion
    timestamp. ``stats['_nba']`` retains the original provider identity, reviewed
    scope and actual observation time. A zero-minute row is not classified DNP.
    Conflicting identities reject the entire batch before any persistence.
    """
    from app.services.game_log_fields import number

    observed = _observed(observed_at)
    if not isinstance(crosswalk, ReviewedPlayerCrosswalk):
        raise ValueError("An explicitly reviewed player crosswalk is required")
    local_ids = [str(UUID(str(value))) for value in crosswalk.values()]
    if (len(set(local_ids)) != len(local_ids)
            or any(nba_id(key) != key for key in crosswalk)):
        raise ValueError("Ambiguous/noncanonical reviewed player crosswalk")
    if not isinstance(season, str) or not re.fullmatch(r"\d{4}-\d{2}", season):
        raise ValueError("Explicit NBA season YYYY-YY required")
    start = int(season[:4])
    if int(season[-2:]) != (start + 1) % 100:
        raise ValueError("Invalid NBA season")
    codes = {"Regular Season": "2", "Playoffs": "4"}
    if competition not in codes:
        raise ValueError("Explicit Regular Season or Playoffs scope required")
    if type(max_records) is not int or not 1 <= max_records <= 1000:
        raise ValueError("Statistics imports must be bounded to at most 1000 rows")
    rows = _rows(payload, "PlayerGameLog")
    if len(rows) > max_records:
        raise ValueError("Statistics batch exceeds reviewed bound")
    directory = {t["abbreviation"]: str(t["id"]) for t in teams.get_teams()}
    fields = {"points": "PTS", "rebounds": "REB", "assists": "AST",
              "minutes": "MIN", "blocks": "BLK", "steals": "STL", "threes": "FG3M"}
    records = {}
    for row in rows:
        athlete = nba_id(row.get("Player_ID"))
        game = nba_id(row.get("Game_ID"), game=True)
        if row.get('WL') not in {'W', 'L'}:
            raise ValueError('NBA statistics require a completed W/L result')
        # Canonical NBA IDs encode competition and the season starting year.
        if not game.startswith("00" + codes[competition] + season[2:4]):
            raise ValueError("NBA game identity does not match reviewed season/competition")
        if athlete not in crosswalk:
            raise ValueError("Unknown NBA/local player crosswalk")
        if row.get("SEASON_ID") is not None and str(row["SEASON_ID"]) != codes[competition] + str(start):
            raise ValueError("Provider season conflicts with reviewed scope")
        day = _date(row.get("GAME_DATE"))
        # Explicit NBA IDs retain season authority across exceptional late
        # finishes (for example the 2019-20 season in October 2020).
        if not date(start, 10, 1) <= day < date(start + 2, 1, 1) or day >= observed.astimezone(EASTERN).date():
            raise ValueError("Unusable NBA game date for reviewed season/observation")
        matchup = row.get("MATCHUP")
        match = re.fullmatch(r"([A-Z]{3}) (vs\.|@) ([A-Z]{3})", matchup) if isinstance(matchup, str) else None
        if not match or match[1] not in directory or match[3] not in directory or match[1] == match[3]:
            raise ValueError("Unsupported/conflicting NBA matchup")
        stats = {}
        for key, field in fields.items():
            raw = row.get(field)
            # Keep NBA clock validation local: the shared ESPN duration parser
            # intentionally supports a different provider's historical shapes.
            if key == "minutes" and isinstance(raw, str) and ":" in raw:
                if not re.fullmatch(r"\d+:[0-5]\d(?:\.\d+)?", raw):
                    raw = None
            try:
                stats[key] = number(raw, duration=key == "minutes")
            except OverflowError:
                stats[key] = None
        for key in fields:
            if key != "minutes" and stats[key] is not None and not stats[key].is_integer():
                stats[key] = None
        # Stats duration is minutes or MM:SS, not an unlimited arbitrary number.
        if stats["minutes"] is not None and stats["minutes"] > 100:
            stats["minutes"] = None
        if all(stats[key] is not None for key in ("points", "rebounds", "assists")):
            stats["pra"] = sum(stats[key] for key in ("points", "rebounds", "assists"))
        appearance = bool((stats["minutes"] or 0) > 0 or any(
            (stats[key] or 0) > 0 for key in fields if key != "minutes"))
        stats["_nba"] = dict(season=season, competition=competition,
            nba_player_id=athlete, nba_game_id=game, team_id=directory[match[1]],
            opponent_id=directory[match[3]], observed_at=observed.isoformat(),
            date_precision="eastern_date", game_date=day.isoformat(),
            reviewed_crosswalk=crosswalk.provenance[athlete], appearance=appearance,
            provider="nba_api.stats.playergamelog")
        record = dict(player_id=crosswalk[athlete], sport="NBA", external_game_id=f"nba_com:{game}",
            game_date=datetime.combine(day, time.min, EASTERN).astimezone(UTC).replace(tzinfo=None),
            opponent=match[3], is_home=match[2] == "vs.", stats=stats, source="nba_com_stats")
        key = (athlete, game)
        if key in records and records[key] != record:
            raise ValueError("Conflicting duplicate NBA player/game statistics")
        records[key] = record
    return list(records.values())


def _inspect_live_boxscore_candidates(payload, *, observed_at, crosswalk):
    """Private synthetic candidate parser; never supplies operational evidence.

    played is a string enum, evaluated only after explicit final status. ACTIVE
    alone never means appeared; played=0 alone never means DNP. Unknown reasons
    and conflicting statistics/status remain unknown. No coverage/membership is
    manufactured from the included athletes or their omissions.
    """
    observed = _observed(observed_at)
    game = payload["game"]
    game_id = nba_id(game["gameId"], game=True)
    at = datetime.fromisoformat(game["gameTimeUTC"].replace("Z", "+00:00"))
    if at.tzinfo is None or at >= observed:
        raise ValueError("Invalid game chronology")
    sides = [game["homeTeam"], game["awayTeam"]]
    ids = [nba_id(side["teamId"]) for side in sides]
    if ids[0] == ids[1]:
        raise ValueError("Conflicting game teams")
    final = type(game.get("gameStatus")) is int and game["gameStatus"] == 3 and game.get("gameStatusText") == "Final"
    source = "nba_api.live.boxscore"
    records = [_record("team", identity, {"name": identity}, observed, source) for identity in ids]
    records.append(_record("game", game_id, dict(home_team_id=ids[0], away_team_id=ids[1],
        scheduled_at=at.isoformat(), game_at=at.isoformat(), completed_at=None,
        status="completed" if final else "unfinished"), observed, source, game_id=game_id))
    if not final:
        return {"unvalidated_candidates": records, "issues": ["Unfinished/unrecognized final status: participation withheld."]}
    seen = set()
    for side, team in zip(sides, ids):
        if not isinstance(side.get("players"), list):
            raise ValueError("Missing player collection")
        for player in side["players"]:
            athlete = nba_id(player["personId"])
            if athlete in seen:
                raise ValueError("Duplicate/conflicting player observation")
            seen.add(athlete)
            if athlete not in crosswalk:
                continue
            local = str(UUID(crosswalk[athlete]))
            played, status, reason = player.get("played"), player.get("status"), player.get("notPlayingReason")
            stats = player.get("statistics")
            if stats is None:
                stats = {}
            if not isinstance(stats, dict):
                raise ValueError("Malformed player statistics")
            # Any recorded counting statistic contradicts a nonappearance.
            # Plus/minus aggregates alone are not participation indicators.
            counts = {key: value for key, value in stats.items()
                      if key not in {"plus", "minus", "plusMinusPoints", "minutes", "minutesCalculated"}}
            positive = any(_number(value) and value != 0 for value in counts.values())
            malformed = any(value is not None and not _number(value) for value in counts.values())
            for key in ("minutes", "minutesCalculated"):
                minutes = stats.get(key)
                duration = re.fullmatch(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", minutes) if isinstance(minutes, str) else None
                positive = positive or bool(duration and any(float(v or 0) > 0 for v in duration.groups()))
                malformed = malformed or minutes is not None and duration is None
            state = "unknown"
            if played == "1" and status == "ACTIVE" and not reason and not player.get("notPlayingDescription"):
                state = "appeared"
            elif played == "0" and not positive and not malformed:
                if status == "INACTIVE":
                    state = "inactive"
                elif status == "ACTIVE" and reason == "DNP":
                    state = "dnp"
            records.extend([
                _record("athlete", athlete, {}, observed, source, player_id=local),
                _record("participation", f"{game_id}-{athlete}", {"athlete_id": athlete, "state": state},
                        observed, source, player_id=local, team_id=team, game_id=game_id),
            ])
    return {"unvalidated_candidates": records, "issues": ["Unvalidated synthetic candidates; forbidden for operational ingestion."]}
