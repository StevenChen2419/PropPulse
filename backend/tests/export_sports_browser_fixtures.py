"""Generate invented browser responses through the production offline adapters."""
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from sports_statistics_fixture import fixture, PLAYER
from nba_statistics_fixture import statistics_fixture
from app.services.nba_api_provider import normalize_player_statistics
from app.services.sports_statistics import normalize_artifact, build_sport_summary


def responses():
    now = datetime(2026, 6, 21, 12, tzinfo=timezone.utc)
    result = []
    for sport,role in [('WNBA','player'),('NHL','skater'),('NHL','goalie'),('NFL','player'),('MLB','batter'),('MLB','pitcher'),('NBA','player')]:
        if sport=='NBA':
            payload,crosswalk,season,observed=statistics_fixture(now)
            records=normalize_player_statistics(payload,observed_at=observed,crosswalk=crosswalk,season=season,competition='Regular Season')
            player_id=next(iter(crosswalk.values()))
        else:
            data,mappings=fixture(sport,role)
            season=data['season']
            records=normalize_artifact(data,mappings,season=season)['records']
            player_id=PLAYER
        summary=build_sport_summary(SimpleNamespace(id=player_id,sport=sport),[SimpleNamespace(**r) for r in records],season=season,now=now)
        summary['notes'].append('Invented offline fixture; not live sports coverage.')
        result.append(dict(sport=sport,role=role,player_id=player_id,season=season,summary=summary))
    return result


if __name__=='__main__':
    output=Path(__file__).resolve().parents[2]/'frontend/tests/fixtures/multi-sport-research.json'
    output.write_text(json.dumps(responses(),indent=2),encoding='utf-8')
