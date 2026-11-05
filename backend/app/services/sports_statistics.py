"""Offline source adapters over PlayerGameLog. No transport or implicit DB writes.

Artifacts retain source responses plus explicit request context. NFL week rows
must join exactly one completed schedule game; missing weeks never mean DNP.
"""
from datetime import date, datetime, time, timezone
from statistics import mean
from uuid import UUID
from zoneinfo import ZoneInfo
import re

from app.services.game_log_fields import number, provider_season

SOURCES = {"WNBA": "wehoop_wnba_stats", "NHL": "nhl_web", "NFL": "nflverse", "MLB": "mlb_stats_api"}
METRICS = {
    "WNBA": {"points": "Points", "rebounds": "Rebounds", "assists": "Assists", "threes": "3PM", "minutes": "Minutes"},
    "NHL": {"goals": "Goals", "assists": "Assists", "points": "Points", "shots_on_goal": "SOG", "time_on_ice": "Time on ice"},
    "NFL": {"pass_yds": "Passing yards", "pass_tds": "Passing TDs", "rush_yds": "Rushing yards", "rush_tds": "Rushing TDs", "reception_yds": "Receiving yards", "receptions": "Receptions", "receiving_tds": "Receiving TDs"},
    "MLB": {"hits": "Hits", "runs": "Runs", "rbis": "RBIs", "total_bases": "Total bases", "home_runs": "Home runs"},
}
EASTERN = ZoneInfo("America/New_York")
SIGNED = {"pass_yds", "rush_yds", "reception_yds"}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def season_name(sport, now=None):
    now = now or datetime.now(timezone.utc)
    year = provider_season(sport, now.astimezone(EASTERN))
    return f"{year-1}-{str(year)[-2:]}" if sport in {"NBA", "NHL"} else str(year)


def validate_season(sport, season):
    pattern = r"\d{4}-\d{2}" if sport in {"NBA", "NHL"} else r"\d{4}"
    if not re.fullmatch(pattern, season) or not 1990 <= int(season[:4]) <= 2100:
        raise ValueError("Invalid sport season")
    if sport in {"NBA", "NHL"} and int(season[-2:]) != (int(season[:4])+1) % 100:
        raise ValueError("Invalid split-year season")
    return season


def reviewed_mappings(entries):
    result, local_sources = {}, set()
    for entry in entries:
        sport = entry.get("sport")
        if (sport not in SOURCES or entry.get("source") != SOURCES[sport]
                or entry.get("verified") is not True or not str(entry.get("provenance") or "").strip()
                or not str(entry.get("identity_evidence") or "").strip()):
            raise ValueError("Reviewed sport/source mapping and independent identity evidence required")
        athlete = str(entry["athlete_id"])
        local = str(UUID(entry["player_id"]))
        if not re.fullmatch(r"00-\d{7}" if sport == "NFL" else r"[1-9]\d{0,9}", athlete):
            raise ValueError("Invalid athlete ID")
        allowed_roles = {"skater", "goalie"} if sport == "NHL" else {"batter", "pitcher"} if sport == "MLB" else {"player"}
        if not entry.get("roles") or set(entry["roles"]) - allowed_roles:
            raise ValueError("Reviewed source roles required")
        key = (sport, athlete)
        if key in result or (sport, local) in local_sources:
            raise ValueError("Conflicting or duplicate reviewed identity")
        result[key] = {**entry, "player_id": local}
        local_sources.add((sport, local))
    # A local Player belongs to exactly one sport.
    locals_seen = {}
    for (sport, _), entry in result.items():
        if entry["player_id"] in locals_seen and locals_seen[entry["player_id"]] != sport:
            raise ValueError("Cross-sport local identity conflict")
        locals_seen[entry["player_id"]] = sport
    return result


def innings_outs(value):
    """Baseball 5.2 means 17 outs, never 5.2 decimal innings."""
    match = re.fullmatch(r"(\d+)(?:\.([012]))?", str(value))
    return int(match[1])*3 + int(match[2] or 0) if match else None


def mlb_completed_schedule_game(game):
    """MLB marks postponed schedule aliases abstract Final too; they are not played."""
    status = game.get("status", {})
    code = status.get("codedGameState")
    detail = str(status.get("detailedState", "")).lower()
    return (status.get("abstractGameState") == "Final"
            and (code is None or code in {"F", "O"})
            and not any(word in detail for word in ("postpon", "suspend", "cancel", "delay")))


def normalize_artifact(artifact, mappings, *, season, competition="Regular Season", max_rows=10000):
    sport = artifact["sport"]
    source = SOURCES[sport]
    validate_season(sport, season)
    if competition not in {"Regular Season", "Playoffs"}:
        raise ValueError("Unsupported competition")
    if artifact.get("source") != source or artifact.get("season") != season or artifact.get("competition") != competition:
        raise ValueError("Artifact source/season/competition mismatch")
    observed = datetime.fromisoformat(artifact["observed_at"].replace("Z", "+00:00"))
    if observed.tzinfo is None or observed > datetime.now(timezone.utc):
        raise ValueError("Valid timezone-aware observation required")
    observed = utc(observed)
    crosswalk = reviewed_mappings(mappings)
    records, seen, role_records, rejected = [], {}, {}, []
    # Each response preserves its request athlete ID and role, not a name match.
    responses = artifact["responses"]
    if len(responses) > max_rows:
        raise ValueError("Response limit exceeded")
    examined = 0
    for response in responses:
        athlete = str(response["athlete_id"])
        mapping = crosswalk.get((sport, athlete))
        if mapping is None:
            rejected.append({"athlete_id": athlete, "reason": "unresolved_mapping"})
            continue
        role = response.get("role")
        if role not in ({"skater", "goalie"} if sport == "NHL" else {"batter", "pitcher"} if sport == "MLB" else {"player"}):
            raise ValueError("Explicit sport-appropriate role required")
        if role not in mapping["roles"]:
            raise ValueError("Response role conflicts with reviewed athlete identity")
        payload = response["payload"]
        if sport == "NHL":
            expected = season[:4] + str(int(season[:4])+1)
            if response.get("request_path") != f'/v1/player/{athlete}/game-log/{expected}/{2 if competition == "Regular Season" else 3}':
                raise ValueError("Exact retained NHL request identity required")
            if str(payload.get("seasonId")) != expected or int(payload.get("gameTypeId", 0)) != (2 if competition == "Regular Season" else 3):
                raise ValueError("NHL response season/type mismatch")
            if str(payload.get("playerId", athlete)) != athlete:
                raise ValueError("NHL athlete mismatch")
            rows = payload["gameLog"]
        elif sport == "MLB":
            groups = payload["stats"]
            expected_group = "hitting" if role == "batter" else "pitching"
            params = response.get("request_params", {})
            if (response.get("request_path") != f'/api/v1/people/{athlete}/stats'
                    or params.get("stats") != "gameLog" or params.get("group") != expected_group
                    or str(params.get("season")) != season):
                raise ValueError("Exact retained MLB request scope required")
            groups = [g for g in groups if g.get("type", {}).get("displayName") == "gameLog" and g.get("group", {}).get("displayName") == expected_group]
            if len(groups) != 1:
                raise ValueError("Exactly one MLB gameLog group required")
            rows = groups[0]["splits"]
        else:
            rows = payload
        for row in rows:
            examined += 1
            if examined > max_rows:
                raise ValueError("Row limit exceeded")
            stats, opponent, team, home, week = {}, None, None, None, None
            if sport == "WNBA":
                # Published wehoop releases use lower-case NBA Stats column names.
                # Retained older uppercase captures are accepted without guessing.
                if len({k.upper() for k in row}) != len(row):
                    raise ValueError("Ambiguous WNBA column aliases")
                row = {k.upper(): v for k,v in row.items()}
                if str(row.get("PLAYER_ID")) != athlete or str(row.get("SEASON_ID")) != ("2" if competition == "Regular Season" else "4") + season:
                    raise ValueError("WNBA athlete/season/type mismatch")
                game, day = str(row["GAME_ID"]), row["GAME_DATE"][:10]
                expected_type = "2" if competition == "Regular Season" else "4"
                if not re.fullmatch(r"10" + expected_type + season[-2:] + r"\d{5}", game):
                    raise ValueError("WNBA game league/season/type mismatch")
                if row.get("WL") not in {"W", "L"}:
                    rejected.append({"game_id": game, "reason": "not_final"}); continue
                fields = {"points": "PTS", "rebounds": "REB", "assists": "AST", "threes": "FG3M", "minutes": "MIN"}
                stats = {k: number(row.get(v), duration=k == "minutes") for k, v in fields.items()}
                if stats["minutes"] is not None and stats["minutes"] > 100:
                    stats["minutes"] = None
                appearance = (stats["minutes"] or 0) > 0 or any((stats[k] or 0) > 0 for k in ("points", "rebounds", "assists", "threes"))
                team = str(row["TEAM_ID"]) if row.get("TEAM_ID") else None
                # Optional published schedule rows establish exact team identities.
                games = [g for g in response.get("schedule", []) if str(g.get("game_id")) == game]
                if games:
                    if len(games) != 1 or team not in {str(games[0].get("home_team_id")), str(games[0].get("away_team_id"))}:
                        raise ValueError("WNBA schedule team identity conflict")
                    home = str(games[0].get("home_team_id")) == team
                    opponent = str(games[0]["away_team_id" if home else "home_team_id"])
            elif sport == "NHL":
                game, day = str(row["gameId"]), row["gameDate"]
                if not re.fullmatch(season[:4] + ("02" if competition == "Regular Season" else "03") + r"\d{4}", game):
                    raise ValueError("NHL game season/type mismatch")
                fields = {"saves": "saves", "time_on_ice": "toi"} if role == "goalie" else {"goals": "goals", "assists": "assists", "points": "points", "shots_on_goal": "shots", "time_on_ice": "toi"}
                stats = {k: number(row.get(v), duration=k == "time_on_ice") for k, v in fields.items()}
                counts = ("saves",) if role == "goalie" else ("goals", "assists", "shots_on_goal")
                appearance = (stats.get("time_on_ice") or 0) > 0 or any((stats.get(k) or 0) > 0 for k in counts)
                opponent, team = row.get("opponentAbbrev"), row.get("teamAbbrev")
                home = {"H": True, "R": False}.get(row.get("homeRoadFlag"))
            elif sport == "NFL":
                if response.get("summary_level") != "week":
                    raise ValueError("NFL adapter accepts week-level assets only")
                if str(row.get("player_id")) != athlete or str(row.get("season")) != season or row.get("season_type") != ("REG" if competition == "Regular Season" else "POST"):
                    raise ValueError("NFL athlete/season/type mismatch")
                week = row.get("week")
                if not str(week).isdigit() or not 1 <= int(week) <= 23:
                    raise ValueError("Invalid NFL week")
                team = row.get("team", row.get("recent_team"))
                opponent = row.get("opponent_team")
                games = [g for g in response.get("schedule", []) if str(g.get("season")) == season and str(g.get("week")) == str(week)
                         and g.get("game_type") == ("REG" if competition == "Regular Season" else g.get("game_type"))
                         and g.get("game_type") in ({"REG"} if competition == "Regular Season" else {"WC", "DIV", "CON", "SB"})
                         and {g.get("home_team"), g.get("away_team")} == {team, opponent}]
                if len(games) != 1 or number(games[0].get("home_score")) is None or number(games[0].get("away_score")) is None:
                    raise ValueError("Weekly NFL row needs exactly one completed matching schedule game")
                match = games[0]
                game, day = match["game_id"], match["gameday"]
                if not re.fullmatch(season + r"_\d{2}_[A-Z0-9]+_[A-Z0-9]+", game):
                    raise ValueError("Invalid official NFL game identity")
                if row.get("game_id") is not None and row["game_id"] != game:
                    raise ValueError("NFL game identity conflict")
                fields = {"pass_yds": "passing_yards", "pass_tds": "passing_tds", "rush_yds": "rushing_yards", "rush_tds": "rushing_tds", "reception_yds": "receiving_yards", "receptions": "receptions", "receiving_tds": "receiving_tds"}
                stats = {k: number(row.get(v), signed=k in SIGNED) for k, v in fields.items()}
                # A weekly performance row records participation, not absent weeks.
                appearance = any(v is not None for v in stats.values())
                home = match["home_team"] == team
            else:
                if str(row.get("player", {}).get("id", athlete)) != athlete or str(row.get("season")) != season:
                    raise ValueError("MLB athlete/season mismatch")
                game, day = str(row["game"]["gamePk"]), row["date"]
                if not re.fullmatch(r"[1-9]\d*", game):
                    raise ValueError("Invalid MLB gamePk")
                games = [g for g in response.get("games", []) if str(g.get("gamePk")) == game
                         and mlb_completed_schedule_game(g)]
                if len(games) != 1 or games[0].get("gameType") not in ({"R"} if competition == "Regular Season" else {"F", "D", "L", "W"}):
                    raise ValueError("MLB split requires final matching competition game")
                raw = row["stat"]
                fields = {"strikeouts": "strikeOuts", "earned_runs": "earnedRuns"} if role == "pitcher" else {"hits": "hits", "runs": "runs", "rbis": "rbi", "total_bases": "totalBases", "home_runs": "homeRuns"}
                stats = {k: number(raw.get(v)) for k, v in fields.items()}
                if role == "pitcher":
                    stats["outs_recorded"] = innings_outs(raw.get("inningsPitched"))
                appearance = (number(raw.get("gamesPlayed")) or 0) > 0
                team, opponent = str(row.get("team", {}).get("id") or "") or None, str(row.get("opponent", {}).get("id") or "") or None
                home = row.get("isHome") if type(row.get("isHome")) is bool else None
            parsed_day = date.fromisoformat(day)
            first_year = int(season[:4])
            if parsed_day.year not in ({first_year, first_year+1} if sport == "NHL" else {first_year, first_year+1} if sport == "NFL" else {first_year}):
                raise ValueError("Game date outside season")
            if sport == "NHL" and not date(first_year, 7, 1) <= parsed_day < date(first_year+1, 7, 1):
                raise ValueError("NHL date outside season")
            if sport == "NFL" and not date(first_year, 7, 1) <= parsed_day < date(first_year+1, 7, 1):
                raise ValueError("NFL date outside season")
            at = datetime.combine(parsed_day, time.min, EASTERN)
            if parsed_day >= observed.astimezone(EASTERN).date() or not appearance:
                rejected.append({"game_id": game, "reason": "not_completed_prior_date_or_no_appearance"}); continue
            if not re.fullmatch(r"[A-Za-z0-9_-]+", game):
                raise ValueError("Invalid game identity")
            meta = dict(provider=source, athlete_id=athlete, season=season, competition=competition,
                        appearance=True, completed=True, reviewed_crosswalk=True, observed_at=observed.isoformat(),
                        role=role, team_id=team, opponent_id=opponent, week=week, date_precision="eastern_date")
            stats.update(_research=meta, completed=True, season_type=competition)
            record = dict(player_id=mapping["player_id"], sport=sport, external_game_id=f"{source}:{game}",
                          game_date=utc(at).replace(tzinfo=None), opponent=opponent, is_home=home, stats=stats, source=source)
            key = (record["player_id"], record["external_game_id"])
            role_key = (*key, role)
            if role_key in role_records:
                if role_records[role_key] != record:
                    raise ValueError("Conflicting duplicate game/role")
                continue
            from copy import deepcopy
            role_records[role_key] = deepcopy(record)
            if key in seen:
                if seen[key] != record:
                    # Two-way MLB players require one combined record with role-specific values.
                    old = seen[key]
                    if (sport == "MLB" and old["stats"]["_research"]["role"] != role
                            and all(old[k] == record[k] for k in record if k != "stats")
                            and all(old["stats"]["_research"].get(k) == v for k,v in meta.items() if k != "role")):
                        old["stats"].update(stats)
                        old["stats"]["_research"]["role"] = "two_way"
                    else:
                        raise ValueError("Conflicting duplicate game")
                continue
            seen[key] = record
            records.append(record)
    return dict(records=records, rejected=rejected, source=source, examined=examined)


def eligible_logs(player, logs, *, season, competition, now, reference):
    result, seen = [], set()
    logs = [log for log in logs if isinstance(log.game_date, datetime)
            and isinstance(log.external_game_id, str) and isinstance(log.stats, dict)
            and isinstance(log.stats.get("_research"), dict)]
    for log in sorted(logs, key=lambda x: (utc(x.game_date), x.external_game_id), reverse=True):
        meta = (log.stats or {}).get("_research", {})
        try:
            observed = datetime.fromisoformat(meta.get("observed_at", ""))
        except (TypeError, ValueError):
            continue
        if (str(log.player_id) != str(player.id) or log.sport != player.sport or log.source != SOURCES.get(player.sport)
                or meta.get("provider") != log.source or not log.external_game_id.startswith(log.source + ":")
                or meta.get("season") != season or meta.get("competition") != competition
                or meta.get("appearance") is not True or meta.get("completed") is not True
                or meta.get("reviewed_crosswalk") is not True or observed.tzinfo is None
                or not meta.get("athlete_id") or meta.get("role") not in {"player", "skater", "goalie", "batter", "pitcher", "two_way"}
                or utc(observed) > min(now, reference) or utc(log.game_date) >= min(now, reference)
                or utc(log.game_date).astimezone(EASTERN).date() >= min(now, reference).astimezone(EASTERN).date()
                or log.external_game_id in seen):
            continue
        seen.add(log.external_game_id)
        result.append(log)
    return result


def build_sport_summary(player, logs, *, season=None, competition="Regular Season", reference=None, now=None):
    if player.sport == "NBA":
        from app.services.nba_season_summary import build_nba_season_summary
        return build_nba_season_summary(player, logs, season=season, competition=competition, reference=reference, now=now)
    now = utc(now or datetime.now(timezone.utc))
    reference = utc(reference or now)
    season = validate_season(player.sport, season or season_name(player.sport, now))
    eligible = eligible_logs(player, logs, season=season, competition=competition, now=now, reference=reference)
    metrics = dict(METRICS[player.sport])
    roles = {log.stats["_research"]["role"] for log in eligible}
    position = str(getattr(player, "position", "") or "").upper()
    if player.sport == "NHL" and (roles == {"goalie"} or not roles and position in {"G", "GOALIE"}):
        metrics = {"saves": "Saves", "time_on_ice": "Time on ice"}
    if player.sport == "MLB" and (roles == {"pitcher"} or not roles and position in {"P", "SP", "RP"}):
        metrics = {"strikeouts": "Strikeouts", "outs_recorded": "Outs recorded", "earned_runs": "Earned runs"}
    elif player.sport == "MLB" and ("two_way" in roles or "pitcher" in roles):
        metrics.update(strikeouts="Strikeouts", outs_recorded="Outs recorded", earned_runs="Earned runs")

    def window(sample):
        out = {"appearances": len(sample)}
        for key in metrics:
            values = [v for row in sample if (v := number(row.stats.get(key), signed=key in SIGNED)) is not None]
            out[key] = dict(average=round(mean(values), 2) if values else None, valid_samples=len(values))
        return out

    def day(row):
        return utc(row.game_date).astimezone(EASTERN).date().isoformat()
    latest = day(eligible[0]) if eligible else None
    gap = (reference.astimezone(EASTERN).date()-date.fromisoformat(latest)).days if latest else None
    opponents = sorted({row.stats["_research"]["opponent_id"] for row in eligible if row.stats["_research"].get("opponent_id")})
    result = dict(status="available" if eligible else "unavailable", sport=player.sport, season=season, competition=competition,
        source=SOURCES[player.sport], metrics=[dict(key=k, label=v) for k,v in metrics.items()],
        coverage_start=day(eligible[-1]) if eligible else None, coverage_end=latest,
        last_observed_at=max(row.stats["_research"]["observed_at"] for row in eligible) if eligible else None,
        recorded_appearances=len(eligible), latest_appearance=latest, date_precision="eastern_date" if eligible else None,
        reference_date=reference.astimezone(EASTERN).date().isoformat(), calendar_day_gap=gap,
        full_intervening_days=max(gap-1, 0) if gap is not None else None, l5=window(eligible[:5]), l10=window(eligible[:10]),
        opponent_history=[dict(opponent_id=opp, l5=window([r for r in eligible if r.stats["_research"].get("opponent_id") == opp][:5]),
            l10=window([r for r in eligible if r.stats["_research"].get("opponent_id") == opp][:10])) for opp in opponents],
        notes=["Recorded coverage may be partial. Missing records do not establish DNP or complete team schedules.",
               "Team rest and back-to-back status unavailable without verified schedule and Event linkage.",
               "Each metric excludes missing values within the latest recorded appearances; seasons and competitions are separate."])
    result['recorded_weeks'] = sorted({r.stats['_research']['week'] for r in eligible
        if player.sport == 'NFL' and r.stats['_research'].get('week') is not None})
    from app.services.statistics_coverage import coverage_from_summary
    result['coverage'] = coverage_from_summary(result, player.sport, now=now)
    return result


def import_records(db, records, *, write=True):
    """Caller owns commit. Reject collisions and stale observations atomically."""
    from sqlalchemy import select
    from contextlib import nullcontext
    from app.models import Player, PlayerGameLog
    if db.new or db.dirty or db.deleted:
        raise ValueError("Import requires clean session")
    counts = dict(new=0, updated=0, unchanged=0, rejected=0)
    with db.begin_nested() if write else nullcontext():
        for record in records:
            player = db.get(Player, record["player_id"])
            if player is None or player.sport != record["sport"]:
                raise ValueError("Exact existing local Player/sport required")
            if record["sport"] == "MLB":
                legacy = db.scalar(select(PlayerGameLog.id).where(PlayerGameLog.player_id == player.id,
                    PlayerGameLog.source == "mlb_stats_api", PlayerGameLog.external_game_id ==
                    record["external_game_id"].removeprefix("mlb_stats_api:")))
                if legacy is not None:
                    raise ValueError("Existing unqualified MLB game requires explicit identity review; no duplicate or overwrite created")
            query = select(PlayerGameLog).where(PlayerGameLog.player_id == player.id,
                PlayerGameLog.external_game_id == record["external_game_id"])
            old = db.scalar(query.with_for_update() if write else query)
            if old is None:
                if write:
                    db.add(PlayerGameLog(**record))
                counts["new"] += 1
            else:
                prior, new = (old.stats or {}).get("_research", {}), record["stats"]["_research"]
                if old.source != record["source"] or old.sport != record["sport"] or any(prior.get(k) != new[k] for k in ("athlete_id", "season", "competition")):
                    raise ValueError("Stored identity/source conflict")
                if prior.get("observed_at", "") > new["observed_at"]:
                    raise ValueError("Stale observation")
                if all(getattr(old, k) == v for k,v in record.items()):
                    counts["unchanged"] += 1
                else:
                    if write:
                        for k,v in record.items():
                            setattr(old,k,v)
                    counts["updated"] += 1
        if write:
            db.flush()
    return counts
