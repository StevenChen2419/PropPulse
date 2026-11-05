"""Plan a bounded PlayerGameLog batch; collection never opens a database.

Execution requires separate human approval of the displayed plan digest. The
import command separately reviews the resulting artifact before database writes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from math import gcd
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_plan(mappings, *, season, competition, date_from, date_to, player_ids=None):
    from app.services.nba_statistics_workflow import validate_scope, no_completed_collection_dates
    empty = no_completed_collection_dates(season, competition, date_from, date_to)
    if not empty:
        validate_scope(season, competition, date_from, date_to)
    selected = set(player_ids or [])
    entries = [entry for entry in mappings if not selected or entry['player_id'] in selected]
    if selected - {entry['player_id'] for entry in entries}:
        raise ValueError('Unknown selected player UUID')
    skipped = [dict(player_id=entry['player_id'], reason='Identity is not reviewed verified')
               for entry in entries if entry.get('review_status') != 'verified']
    entries = [entry for entry in entries if entry.get('review_status') == 'verified']
    if not 1 <= len(entries) <= 100:
        raise ValueError('Select between one and 100 players')
    from app.services.nba_api_provider import verified_crosswalk
    verified_crosswalk([dict(player_id=e['player_id'], nba_player_id=e['nba_player_id'],
        verified=True, provenance=e['provenance']) for e in entries])
    def provider_date(value):
        return datetime.strptime(value, '%Y-%m-%d').strftime('%m/%d/%Y')
    plan = dict(season=season, competition=competition, date_from=date_from,
        date_to=date_to, endpoint='https://stats.nba.com/stats/playergamelog',
        status='no_games_yet' if empty else 'ready',
        request_budget=0 if empty else len(entries), timeout_seconds=10, retries=0,
        max_response_bytes=512_000, max_total_response_bytes=4_000_000,
        redirects=False, min_delay_seconds=2, players=entries, skipped=skipped,
        proxies=False,
        common_parameters=dict(Season=season, SeasonType=competition, LeagueID='00',
            DateFrom=provider_date(date_from), DateTo=provider_date(date_to)))
    plan['requests'] = [] if empty else [dict(method='GET', url=plan['endpoint'],
        parameters={**plan['common_parameters'], 'PlayerID': str(e['nba_player_id'])}) for e in entries]
    return plan


def plan_digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def collect(plan, *, approved_plan_sha256, output):
    """Explicit transport entry point. No retries, redirects, DB or research hooks."""
    if approved_plan_sha256 != plan_digest(plan):
        raise ValueError('Approval must match the exact displayed plan digest')
    if plan.get('status') == 'no_games_yet':
        raise ValueError('No completed Regular Season Eastern dates; preview again after games complete')
    if any(e.get('review_status') != 'verified' for e in plan['players']):
        raise ValueError('Resolve and review every identity before collection')
    from nba_api.library.http import NBAHTTP
    from nba_api.stats.endpoints.playergamelog import PlayerGameLog
    import requests

    class BoundedSession(requests.Session):
        attempts = 0
        last_finished = None
        received_bytes = 0

        def __init__(self):
            super().__init__()
            self.trust_env = False
            self.requested_players = set()

        def get(self, url, **kwargs):
            parsed = urlsplit(url)
            if (parsed.scheme, parsed.hostname, parsed.path) != ('https', 'stats.nba.com', '/stats/playergamelog'):
                raise ValueError('Unexpected provider endpoint')
            if self.attempts >= plan['request_budget']:
                raise ValueError('Request budget exhausted')
            if kwargs.get('proxies'):
                raise ValueError('Proxy routing is not permitted')
            parameters = dict(kwargs.get('params', []))
            athlete = str(parameters.get('PlayerID'))
            if (athlete not in {str(e['nba_player_id']) for e in plan['players']}
                    or athlete in self.requested_players
                    or parameters != {**plan['common_parameters'], 'PlayerID': athlete}):
                raise ValueError('Request parameters differ from approved NBA scope')
            if self.last_finished is not None:
                time.sleep(max(0, 2 - (time.monotonic() - self.last_finished)))
            self.attempts += 1
            self.requested_players.add(athlete)
            try:
                response = super().get(url, **{**kwargs, 'timeout': 10, 'allow_redirects': False, 'stream': True})
                receipt = dict(nba_player_id=athlete, status_code=response.status_code,
                    observed_at=datetime.now(timezone.utc).isoformat(), body='', truncated=False)
                artifact['http_responses'].append(receipt)
                try:
                    body = bytearray()
                    limit = min(plan['max_response_bytes'], plan['max_total_response_bytes']-self.received_bytes)
                    if limit <= 0:
                        raise ValueError('NBA response byte ceiling reached')
                    for chunk in response.iter_content(chunk_size=gcd(4096, limit)):
                        self.received_bytes += len(chunk)
                        body.extend(chunk)
                        if len(body) >= limit:
                            receipt['truncated'] = True
                            raise ValueError('NBA response byte ceiling reached')
                    # nba_api consumes response.text after our bounded stream closes.
                    response._content = bytes(body)
                    response._content_consumed = True
                    receipt['body'] = response.text
                    response.raise_for_status()
                    if response.is_redirect:
                        raise ValueError('Provider redirect rejected')
                    return response
                finally:
                    response.close()
            finally:
                self.last_finished = time.monotonic()

    # Exclusive creation prevents overwriting previously collected evidence.
    with Path(output).open('x', encoding='utf-8') as stream, BoundedSession() as session:
        artifact = {key: plan[key] for key in ('season', 'competition', 'date_from', 'date_to')}
        artifact['responses'] = []
        artifact['failures'] = []
        artifact['http_responses'] = []
        NBAHTTP.set_session(session)
        try:
            for entry in plan['players']:
                try:
                    payload = PlayerGameLog(entry['nba_player_id'], season=plan['season'],
                        season_type_all_star=plan['competition'], league_id_nullable='00',
                        date_from_nullable=plan['common_parameters']['DateFrom'],
                        date_to_nullable=plan['common_parameters']['DateTo'],
                        timeout=10, proxy=False).nba_response.get_dict()
                except Exception as exc:
                    receipt = next((r for r in reversed(artifact['http_responses'])
                        if r['nba_player_id'] == str(entry['nba_player_id'])), {})
                    artifact['failures'].append(dict(player_id=entry['player_id'],
                        nba_player_id=entry['nba_player_id'],
                        observed_at=datetime.now(timezone.utc).isoformat(),
                        http_status=receipt.get('status_code'),
                        error='access_denied' if receipt.get('status_code') in {401,403} else type(exc).__name__))
                    if session.received_bytes >= plan['max_total_response_bytes']:
                        break
                    continue
                artifact['responses'].append(dict(nba_player_id=entry['nba_player_id'],
                    observed_at=datetime.now(timezone.utc).isoformat(), payload=payload))
        finally:
            NBAHTTP.set_session(None)
            artifact['request_count'] = session.attempts
            artifact['response_bytes'] = session.received_bytes
            # Retain successful responses if a later request fails. A partial
            # artifact cannot import an absent selected player.
            json.dump(artifact, stream, indent=2, allow_nan=False)
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', required=True)
    parser.add_argument('--season', required=True)
    parser.add_argument('--competition', required=True)
    parser.add_argument('--date-from', required=True)
    parser.add_argument('--date-to', required=True)
    parser.add_argument('--player', action='append')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approved-plan-sha256')
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        plan = build_plan(json.loads(Path(args.mapping).read_text(encoding='utf-8-sig')),
            season=args.season, competition=args.competition, date_from=args.date_from,
            date_to=args.date_to, player_ids=args.player)
        if args.execute:
            if not args.output:
                raise ValueError('Explicit artifact destination required')
            artifact = collect(plan, approved_plan_sha256=args.approved_plan_sha256, output=args.output)
            print(json.dumps(dict(responses=len(artifact['responses']),
                artifact_sha256=hashlib.sha256(Path(args.output).read_bytes()).hexdigest())))
        else:
            print(json.dumps(dict(plan=plan, plan_sha256=plan_digest(plan)), indent=2))
        return 0
    except Exception as exc:
        # Transport/DB/library exceptions can contain credentials or routing data.
        print(json.dumps({'status': 'rejected', 'reason': str(exc) if type(exc) is ValueError else type(exc).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
