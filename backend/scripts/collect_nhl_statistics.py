"""Reusable Phase 8 NHL profile/game-log collection for reviewed identities only.

Collection produces an offline artifact; it never opens a database. The bounded
streaming/no-redirect transport follows the retained Phase 8 expansion collector.
"""
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path

from app.services.sports_statistics import reviewed_mappings, validate_season


def build_plan(mappings, *, season, competition='Regular Season'):
    validate_season('NHL', season)
    if competition != 'Regular Season':
        raise ValueError('NHL collection supports regular season only')
    entries = list(reviewed_mappings(mappings).values())
    if not entries or len(entries) > 100 or any(e['sport'] != 'NHL' or len(e['roles']) != 1 for e in entries):
        raise ValueError('Select 1..100 reviewed NHL athletes with one source role each')
    requests = []
    for entry in entries:
        athlete = entry['athlete_id']
        requests.extend([dict(athlete_id=athlete, path=f'/v1/player/{athlete}/landing'),
            dict(athlete_id=athlete, path=f'/v1/player/{athlete}/game-log/{season[:4]}20{season[-2:]}/2')])
    return dict(source='nhl_web', season=season, competition=competition, players=entries,
                requests=requests, request_budget=len(requests), max_response_bytes=2_000_000,
                max_bytes=len(requests)*2_000_000, retries=0, redirects=False)


def plan_digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def collect(plan, *, approved_plan_sha256, output):
    if approved_plan_sha256 != plan_digest(plan):
        raise ValueError('Approval must match exact NHL collection plan')
    import httpx
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    artifact = dict(sport='NHL', source='nhl_web', season=plan['season'], competition=plan['competition'],
                    responses=[], profiles=[], failures=[], request_count=0)
    entries = {str(e['athlete_id']): e for e in plan['players']}
    verified = set()
    total_bytes = 0
    # Claim before transport. Repeated executions cannot overwrite observations.
    with output.open('x', encoding='utf-8') as handle:
        try:
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False,
                              headers={'Accept-Encoding': 'identity'}) as client:
                for req in plan['requests']:
                    athlete = str(req['athlete_id'])
                    profile = req['path'].endswith('/landing')
                    if not profile and athlete not in verified:
                        artifact['failures'].append(dict(athlete_id=athlete, reason='profile_not_verified'))
                        continue
                    if artifact['request_count'] >= plan['request_budget']:
                        raise ValueError('NHL request ceiling exceeded')
                    artifact['request_count'] += 1
                    try:
                        with client.stream('GET', 'https://api-web.nhle.com'+req['path']) as response:
                            response.raise_for_status()
                            if response.is_redirect:
                                raise ValueError('Redirect prohibited')
                            body = bytearray()
                            for part in response.iter_bytes(chunk_size=4096):
                                total_bytes += len(part)
                                body.extend(part)
                                if len(body) > plan['max_response_bytes'] or total_bytes > plan['max_bytes']:
                                    raise ValueError('NHL response ceiling exceeded')
                            payload = json.loads(body)
                        if profile:
                            role = 'goalie' if payload.get('position') == 'G' else 'skater'
                            if (str(payload.get('playerId')) != athlete or payload.get('position') not in {'C','L','R','D','G'}
                                    or entries[athlete]['roles'] != [role]
                                    or not any(str(s.get('season')) == plan['season'][:4]+'20'+plan['season'][-2:]
                                        and s.get('gameTypeId') == 2 and s.get('leagueAbbrev') == 'NHL'
                                        and (s.get('gamesPlayed') or 0) > 0 for s in payload.get('seasonTotals', []))):
                                raise ValueError('NHL profile identity/role/completed season unavailable')
                            verified.add(athlete)
                            artifact['profiles'].append(dict(athlete_id=athlete, payload=payload,
                                observed_at=datetime.now(timezone.utc).isoformat()))
                        else:
                            artifact['responses'].append(dict(athlete_id=athlete, role=entries[athlete]['roles'][0],
                                request_path=req['path'], payload=payload))
                    except Exception as exc:
                        artifact['failures'].append(dict(athlete_id=athlete,
                            reason=str(exc) if type(exc) is ValueError else type(exc).__name__))
        finally:
            artifact['observed_at'] = datetime.now(timezone.utc).isoformat()
            json.dump(artifact, handle, indent=2)
    return artifact
