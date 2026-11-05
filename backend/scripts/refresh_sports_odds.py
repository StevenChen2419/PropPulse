"""Exact offline Odds API plan; execution requires separately approved plan hash.

Retained coverage JSON specifies selected sports, exact events, known markets or
explicitly approved probes, and retained roster directories. Dry-run never calls providers.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.ingestion_control import RequestBudget, odds_ingestion_lock


def configured_sports():
    tree = ast.parse(Path(__file__).with_name('fetch_odds.py').read_text(encoding='utf-8'))
    return next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'SPORT_CONFIG' for target in node.targets))


def plan_refresh(coverage, sports, *, max_credits, max_requests=100):
    config = configured_sports()
    if len(sports) != len(set(sports)) or not sports or max_credits < 0 or max_requests < 1:
        raise ValueError('Invalid sports or budget')
    plans, credits, requests = {}, 0, []
    for key in sports:
        if key not in config:
            raise ValueError('Unconfigured sport key')
        entry = coverage.get('sports', {}).get(key, {})
        markets = entry.get('markets', [])
        if len(markets) != len(set(markets)) or set(markets) - set(config[key]['markets']):
            raise ValueError('Unconfigured or duplicate markets')
        events = entry.get('events', [])
        if len({e['id'] for e in events}) != len(events):
            raise ValueError('Duplicate events')
        # A sports listing does not prove tier entitlement. Only retained event
        # market responses/rejections can establish accessible/blocked coverage.
        # A probe authorizes a bounded attempt without claiming entitlement.
        state = entry.get('access', 'unknown')
        if state not in {'accessible', 'probe', 'unsupported', 'unknown', 'no_games'}:
            raise ValueError('Invalid access state')
        if state == 'accessible' and (not entry.get('evidence') or not markets):
            raise ValueError('Accessible markets require retained tier evidence')
        if state == 'probe' and (not entry.get('discovery_evidence') or not markets or not events):
            raise ValueError('Explicit market probes require retained event discovery evidence')
        approved_events = events if state in {'accessible', 'probe'} else []
        for event in approved_events:
            if not isinstance(event['id'], str) or not event['id'].isalnum():
                raise ValueError('Invalid event ID')
            if any(not event.get(k) for k in ('home_team', 'away_team', 'commence_time')):
                raise ValueError('Complete event metadata required')
        cost = len(markets) * len(approved_events)  # one US region, retries disabled
        credits += cost
        if state in {'accessible', 'probe'}:
            requests.append(dict(method='GET', path=f'/sports/{key}/events', max_credits=0))
            requests.extend(dict(method='GET', path=f'/sports/{key}/events/{event["id"]}/odds',
                markets=markets, regions='us', max_credits=len(markets)) for event in approved_events)
        plans[key] = dict(sport=config[key]['label'], access=state, markets=markets,
            events=approved_events, max_credits=cost, evidence=entry.get('evidence'),
            discovery_evidence=entry.get('discovery_evidence'),
            roster_directory=entry.get('roster_directory', {}))
    if requests:
        requests.insert(0, dict(method='GET', path='/sports', max_credits=0))
    if credits > max_credits or len(requests) > max_requests:
        raise ValueError('Plan exceeds request/credit budget')
    return dict(provider='the_odds_api', regions='us', sports=plans, max_credits=max_credits,
        estimated_max_credits=credits, max_requests=max_requests, planned_max_requests=len(requests), requests=requests,
        quota_reserve=50, retries=0, roster_http_requests=0, database_target=coverage.get('database_target'),
        coverage_sha256=hashlib.sha256(json.dumps(coverage, sort_keys=True).encode()).hexdigest())


def plan_digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def execute(plan, approved_digest, *, allow_player_changes=True, strict_scope=False):
    if approved_digest != plan_digest(plan):
        raise ValueError('Approval must match exact plan digest')
    if not plan['requests']:
        return dict(status='no_approved_coverage', provider_requests=0, database_writes=0,
            sports={key: dict(coverage=item['access']) for key,item in plan['sports'].items()})
    # This import reads provider settings; dry-run never imports it or opens DB.
    from scripts import fetch_odds as importer
    if strict_scope and plan['quota_reserve'] < importer.MIN_REMAINING_CREDITS:
        raise ValueError('Plan reserve below configured provider reserve; preview again with configured reserve')
    from sqlalchemy.engine import make_url
    target = make_url(str(importer.engine.url))
    if plan.get('database_target') != f'{target.host}:{target.port or 5432}/{target.database}':
        raise ValueError('Approval must name exact configured database target')
    original_config, original_get = importer.SPORT_CONFIG, importer.get
    importer.SPORT_CONFIG = {key: {**original_config[key], 'markets': {
        market: original_config[key]['markets'][market] for market in item['markets']}}
        for key,item in plan['sports'].items()}
    importer.ACTIVE_BUDGET = RequestBudget(plan['max_requests'], plan['max_credits'], plan['quota_reserve'])
    remaining_requests = list(plan['requests'])
    confirmed_costs = True
    def bounded_get(client, path, params, **kwargs):
        nonlocal confirmed_costs
        if strict_scope:
            match = next((r for r in remaining_requests if r['path'] == path), None)
            if match is None:
                raise ValueError('Request outside approved plan')
            if match.get('markets') and (params.get('markets') != ','.join(match['markets']) or params.get('regions') != 'us'):
                raise ValueError('Markets outside approved plan')
            if match['max_credits'] and importer.ACTIVE_BUDGET.remaining is None:
                raise ValueError('Confirmed remaining quota required')
            remaining_requests.remove(match)
        result = original_get(client, path, params, max_attempts=1)
        if strict_scope:
            try:
                if int(result[2].get('x-requests-last')) < 0:
                    raise ValueError('Invalid cost')
            except (TypeError, ValueError):
                confirmed_costs = False
            try:
                remaining = int(result[2].get('x-requests-remaining'))
                if remaining < 0:
                    raise ValueError('Invalid quota')
            except (TypeError, ValueError):
                importer.ACTIVE_BUDGET.remaining = None
                importer.ACTIVE_BUDGET.stopped = True
                importer.ACTIVE_BUDGET.reason = 'unconfirmed_quota'
        return result
    importer.get = bounded_get
    statuses = {key: importer.make_sport_status(key) for key in importer.SPORT_CONFIG}
    rows, directories = {}, {}
    try:
        with odds_ingestion_lock(importer.engine) as acquired:
            if not acquired:
                return dict(status='skipped_locked', sports={})
            with importer.httpx.Client() as client:
                active = importer.verify_key_and_sports(client, statuses)
                for key, item in plan['sports'].items():
                    status = statuses[key]
                    rows[key], directories[key] = [], item['roster_directory']
                    if item['access'] not in {'accessible', 'probe'}:
                        status['coverage'] = item['access']
                        continue
                    try:
                        discovered = importer.fetch_events(client, key, status,
                            approved_event_ids={e['id'] for e in item['events']}) if active and status['active'] else []
                        if importer.ACTIVE_BUDGET.remaining is None:
                            raise ValueError('Provider remaining quota unknown; paid requests prohibited')
                        by_id = {e['id']: e for e in discovered}
                        events = []
                        for approved in item['events']:
                            current = by_id.get(approved['id'])
                            if current and all(current.get(k) == approved[k] for k in ('home_team', 'away_team', 'commence_time')):
                                events.append(current)
                            else:
                                status['warnings'].append('Approved event missing or metadata changed: ' + approved['id'])
                        rows[key] = importer.fetch_player_props(client, key, events, status)
                        status['coverage'] = 'observed' if rows[key] else 'no_offers'
                    except Exception as exc:
                        status['errors'].append('Sport refresh failed: ' + type(exc).__name__)
                        status['coverage'] = 'failed'
            # Existing per-sport transactions preserve IDs, offers and snapshots.
            persist_options = dict(allow_player_changes=allow_player_changes)
            if strict_scope:
                persist_options['sport_keys'] = {key for key, item in plan['sports'].items()
                    if item['events'] and item['access'] in {'accessible', 'probe'} and statuses[key]['coverage'] != 'failed'}
            importer.persist_sports(statuses, rows, directories, **persist_options)
            for key in statuses:
                importer.finalize_sport_status(statuses[key], plan['sports'][key]['events'], rows[key], bool(importer.API_KEY))
            report = dict(status='finished', sports=statuses, **importer.ACTIVE_BUDGET.report())
            if strict_scope:
                report['credits_consumed'] = report['credits_accounted'] if confirmed_costs else 'unknown'
            importer.write_status(importer.aggregate_status(statuses, [], []))
            return report
    except Exception as exc:
        if not strict_scope:
            raise
        return dict(status='failed', reason=type(exc).__name__, sports=statuses,
            credits_consumed=importer.ACTIVE_BUDGET.credits if confirmed_costs else 'unknown',
            **importer.ACTIVE_BUDGET.report())
    finally:
        importer.SPORT_CONFIG, importer.get, importer.ACTIVE_BUDGET = original_config, original_get, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sports', nargs='+', choices=list(configured_sports()), default=list(configured_sports()))
    parser.add_argument('--coverage', type=Path, help='Retained tier/event/roster evidence JSON; absent means unknown coverage')
    parser.add_argument('--max-credits', type=int, default=0)
    parser.add_argument('--max-requests', type=int, default=100)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--execute-approved', help='Separately approved SHA256; includes exact provider requests and DB writes')
    args = parser.parse_args(argv)
    try:
        coverage = json.loads(args.coverage.read_text(encoding='utf-8')) if args.coverage else {}
        plan = plan_refresh(coverage, args.sports, max_credits=args.max_credits, max_requests=args.max_requests)
        result = execute(plan, args.execute_approved) if args.execute_approved else dict(mode='dry-run', plan=plan,
            plan_sha256=plan_digest(plan), provider_requests=0, database_writes=0,
            limitation='Unknown/unsupported sports are not probed for player props. Approve discovery separately before supplying retained market evidence.')
        print(json.dumps(result, indent=2, default=str))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps(dict(status='rejected', reason=str(exc))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
