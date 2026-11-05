"""Invented offline Phase 5C browser data; disposable test database only."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models import Event, Player, Prop
from app.services.nba_api_provider import normalize_team_games, verified_crosswalk
from app.services.nba_evidence_service import _test_target, append_normalized_evidence
from app.services.nba_statistics_service import import_player_statistics

PLAYER = "5c000000-0000-4000-8000-000000000001"
EVENT = "5c000000-0000-4000-8000-000000000002"
PROP = "5c000000-0000-4000-8000-000000000003"
UNMAPPED_EVENT = "5c000000-0000-4000-8000-000000000004"
UNMAPPED_PROP = "5c000000-0000-4000-8000-000000000005"


def result_set(name, rows):
    return {"resultSets": [dict(name=name, headers=list(rows[0]), rowSet=[list(row.values()) for row in rows])]}


def seed_matchup(db, observed):
    _test_target(db)
    eastern = ZoneInfo("America/New_York")
    day = observed.astimezone(eastern).date()
    reference = datetime.combine(day, time(23, 59, 59), eastern).astimezone(timezone.utc)
    last_day = day - timedelta(days=1)
    start = last_day.year if last_day.month >= 10 else last_day.year - 1
    season = f"{start}-{str(start+1)[-2:]}"
    crosswalk = verified_crosswalk([dict(nba_player_id="1627759", player_id=PLAYER, verified=True,
        provenance="Invented offline Phase 5C UUID; no real performance or team coverage")])
    db.add(Player(id=PLAYER, name="Fixture NBA Matchup (invented)", team="Boston Celtics", team_abbr="BOS", sport="NBA"))
    for event_id, prop_id, home in ((EVENT, PROP, "Orlando Magic"),
                                     (UNMAPPED_EVENT, UNMAPPED_PROP, "Unmapped fixture participant")):
        db.add(Event(id=event_id, provider="the_odds_api", sport_key="basketball_nba",
                     provider_event_id=f"invented-5c-{event_id}", home_team=home,
                     away_team="Boston Celtics", scheduled_start_at=reference))
        db.flush()
        db.add(Prop(id=prop_id, player_id=PLAYER, event_id=event_id, prop_type="points",
                    line=20.5, sportsbook="Invented fixture unavailable", is_active=False,
                    odds_sport_key="basketball_nba", odds_event_id=f"invented-5c-{event_id}",
                    game_time=reference, opponent=home, is_home=False))
    db.flush()
    rows = [dict(Player_ID=1627759, Game_ID=f"002{str(start)[-2:]}{90001+i:05d}",
                 SEASON_ID=f"2{start}", GAME_DATE=(last_day-timedelta(days=i)).isoformat(), WL='W',
                 MATCHUP="BOS vs. ORL", MIN=None if i == 1 else 30+i,
                 PTS=None if i == 2 else i*2, REB=None if i == 3 else i,
                 AST=0 if i == 0 else i+1) for i in range(12)]
    imported = import_player_statistics(db, result_set("PlayerGameLog", rows), observed_at=observed,
        crosswalk=crosswalk, season=season, competition="Regular Season")
    assert imported["inserted"] == 12
    team_rows = [dict(TEAM_ID=1610612738, GAME_ID=rows[0]["Game_ID"], GAME_DATE=last_day.isoformat(),
                      MATCHUP="BOS vs. ORL", WL="W", PTS=100),
                 dict(TEAM_ID=1610612753, GAME_ID=rows[0]["Game_ID"], GAME_DATE=last_day.isoformat(),
                      MATCHUP="ORL @ BOS", WL="L", PTS=90)]
    normalized = normalize_team_games(result_set("LeagueGameLog", team_rows), observed_at=observed)
    assert not normalized["issues"]
    scope = dict(provider="nba_com", crosswalk=crosswalk, sport="NBA", start_date=last_day.isoformat(),
                 end_date=day.isoformat(), team_ids=["1610612738", "1610612753"], now=observed)
    dry = append_normalized_evidence(db, normalized["records"], **scope)
    appended = append_normalized_evidence(db, normalized["records"], **scope,
        write=True, expected_digest=dry["digest"])
    assert appended["inserted"] == len(normalized["records"])
    return dict(player_id=PLAYER, event_id=EVENT, prop_id=PROP, unmapped_prop_id=UNMAPPED_PROP,
                reference_date=day.isoformat(), last_game_date=last_day.isoformat(),
                season=season, synthetic=True, real_response_obtained=False)
