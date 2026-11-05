"""Invented NBA Stats-shaped values, never real player performance/coverage."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models import Player
from app.services.nba_api_provider import verified_crosswalk
from app.services.nba_statistics_service import import_player_statistics

PLAYER_ID = "5b000000-0000-4000-8000-000000000001"


def statistics_fixture(reference=None):
    reference = reference or datetime(2026, 10, 18, 18, tzinfo=timezone.utc)
    # Keep fixture season explicit; relative dates are only for browser evaluation.
    end = reference.astimezone(ZoneInfo("America/New_York")).date() - timedelta(days=3)
    start_year = end.year if end.month >= 10 else end.year - 1
    season = f"{start_year}-{str(start_year+1)[-2:]}"
    rows = [dict(Player_ID=1627759, Game_ID=f"002{str(start_year)[-2:]}{i+1:05d}",
                 SEASON_ID=f"2{start_year}", GAME_DATE=(end-timedelta(days=i)).isoformat(), WL='W',
                 MATCHUP="BOS vs. ORL" if i < 6 else "LAL @ BOS",
                 MIN=30+i if i != 1 else None, PTS=i*2 if i != 2 else None,
                 REB=i if i != 3 else None, AST=0 if i == 0 else i+1)
            for i in range(12)]
    headers = list(rows[0])
    payload = {"resultSets": [{"name": "PlayerGameLog", "headers": headers,
                               "rowSet": [[row[key] for key in headers] for row in rows]}]}
    crosswalk = verified_crosswalk([dict(nba_player_id="1627759", player_id=PLAYER_ID,
        verified=True, provenance="Invented offline Phase 5B fixture, not real statistical coverage")])
    return payload, crosswalk, season, reference-timedelta(hours=1)


def seed_statistics(db, reference=None):
    db.add(Player(id=PLAYER_ID, name="Fixture NBA Statistics (invented)",
                  team="Boston Celtics", team_abbr="BOS", sport="NBA"))
    db.flush()
    data, crosswalk, season, observed = statistics_fixture(reference)
    arguments = dict(observed_at=observed, crosswalk=crosswalk, season=season,
                     competition="Regular Season")
    first = import_player_statistics(db, data, **arguments)
    replay = import_player_statistics(db, data, **arguments)
    assert first["inserted"] == 12 and replay["unchanged"] == 12
    return {"player_id": PLAYER_ID, "season": season, "synthetic": True}
