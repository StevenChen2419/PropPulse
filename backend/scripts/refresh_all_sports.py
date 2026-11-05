"""Offline unified refresh preview; execute only an explicitly approved exact digest.

No application lifespan, discovery requests, or database comparison runs in preview.
Statistics collection and import remain separate plans: new bytes require review.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import refresh_sports_statistics as statistics
from scripts import refresh_sports_odds as odds
from app.services.sports_statistics import SOURCES, season_name, normalize_artifact
from app.services.ingestion_control import atomic_json

BACKEND = Path(__file__).resolve().parents[1]
RUNS = BACKEND / 'data/odds_runs'
SPORTS = dict(nba='basketball_nba', wnba='basketball_wnba', nhl='icehockey_nhl',
              nfl='americanfootball_nfl', mlb='baseball_mlb')
LIMITATIONS = dict(wnba='Published wehoop download and schedule descriptor required; release may be partial.',
    nfl='Published nflverse weekly dataset and completed schedule joins required.',
    mlb='Retained StatsAPI gameLog and final schedule required; legacy overlaps require separate review.')


def select_sports(values):
    if 'all' in values:
        if values != ['all']:
            raise ValueError('Use all alone')
        return list(SPORTS)
    if not values or set(values) - SPORTS.keys():
        raise ValueError('Unsupported sports')
    return list(dict.fromkeys(values))


def invoke(entry, args):
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = entry(args)
    try:
        result = json.loads(stdout.getvalue() or stderr.getvalue())
    except ValueError:
        raise ValueError('Existing workflow returned no structured result') from None
    if code:
        raise ValueError(result.get('reason') or result.get('error') or 'Existing workflow rejected scope')
    return result


def read(path):
    path = Path(path)
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError('Input exceeds 50 MiB')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def coverage(records, nba=False):
    key = '_nba' if nba else '_research'
    days = [(r['game_date'].replace(tzinfo=timezone.utc) if r['game_date'].tzinfo is None else r['game_date'])
            .astimezone(ZoneInfo('America/New_York')).date().isoformat() for r in records]
    return dict(statistics_last_observed=max((r['stats'][key]['observed_at'] for r in records), default='unknown'),
        latest_completed_game_represented=max(days, default='unknown'), coverage_start=min(days, default='unknown'),
        game_date_precision='eastern_date',
        players_represented=len({r['player_id'] for r in records}), validated_game_logs=len(records),
        coverage_complete='unknown')


def statistics_plan(sport, spec, target):
    source = 'nba_com_stats' if sport == 'nba' else SOURCES[sport.upper()]
    season = spec.get('season', season_name(sport.upper()))
    operation = dict(sport=sport, kind='statistics', source=source, season=season,
                     provider_requests=0, database_writes=0)
    if not spec:
        return operation | dict(status='skipped', reason='Exact statistics scope/mapping/artifact required')
    action = spec.get('action', 'artifact')
    if type(spec.get('max_rows', 1000)) is not int or not 1 <= spec.get('max_rows', 1000) <= 10000:
        raise ValueError('max_rows must be 1..10000')
    if action not in {'artifact', 'collect'}:
        raise ValueError('Statistics action must be artifact or collect')
    if action == 'collect' and sport in LIMITATIONS:
        return operation | dict(status='unsupported', reason=LIMITATIONS[sport], action=action)
    mappings = read(spec['mapping'])
    if action == 'collect':
        output = Path(spec['output']).resolve()
        if not output.is_relative_to(RUNS.resolve()) or output.exists():
            raise ValueError('Collection output must be a fresh file under backend/data/odds_runs')
        if sport == 'nba':
            from scripts.collect_nba_statistics import build_plan
            plan = build_plan(mappings, season=season, competition=spec.get('competition', 'Regular Season'),
                date_from=spec['date_from'], date_to=spec['date_to'], player_ids=spec.get('players'))
        else:
            from scripts.collect_nhl_statistics import build_plan
            selected = [m for m in mappings if not spec.get('players') or m['player_id'] in spec['players']]
            if set(spec.get('players', [])) - {m['player_id'] for m in selected}:
                raise ValueError('Selected NHL UUID absent from reviewed mappings')
            plan = build_plan(selected, season=season, competition=spec.get('competition', 'Regular Season'))
        return operation | dict(status=plan.get('status', 'ready'), action=action, collection_plan=plan,
            reason='No completed Regular Season Eastern dates available; no collection or import' if plan.get('status') == 'no_games_yet' else None,
            mapping_sha256=statistics.digest(mappings), output=str(output),
            max_rows=spec.get('max_rows', 1000 if sport == 'nba' else 10000),
            provider_requests=plan['request_budget'], note='Collection only; preview and approve resulting artifact before import')
    if not target:
        raise ValueError('Artifact imports require exact --database-target in preview')
    if sport == 'nba':
        from scripts.import_nba_statistics import _load
        from app.services.nba_statistics_workflow import prepare_batch, database_target
        from app.config import settings
        db_target = database_target(settings.DATABASE_URL)
        if target != f"{db_target['host']}:{db_target['port']}/{db_target['database']}":
            raise ValueError('NBA target differs from configured development database')
        artifact_path, = spec['artifacts']
        artifact, artifact_hash = _load(Path(artifact_path))
        _, mapping_hash = _load(Path(spec['mapping']))
        params = dict(season=season, competition=spec.get('competition', 'Regular Season'),
            date_from=spec['date_from'], date_to=spec['date_to'], player_ids=spec.get('players'),
            max_rows=spec.get('max_rows', 1000))
        batch = prepare_batch(mappings, artifact, **params)
        records = [r for p in batch['players'] for r in p['records']]
        scope = dict(database_target=db_target, mapping_sha256=mapping_hash, artifact_sha256=artifact_hash,
            **{k: v for k,v in params.items() if k != 'player_ids'},
            player_ids=sorted(p['player_id'] for p in batch['players']))
        command = ['--mapping', spec['mapping'], '--artifact', artifact_path, '--season', season,
            '--competition', params['competition'], '--date-from', params['date_from'], '--date-to', params['date_to'],
            '--max-rows', str(params['max_rows'])]
        for player in scope['player_ids']:
            command += ['--player', player]
        details = coverage(records, nba=True)
        rejected = 0
        rejections = []
    else:
        command = ['--sports', sport, '--season', season, '--mapping', spec['mapping'],
            '--competition', spec.get('competition', 'Regular Season'), '--max-rows', str(spec.get('max_rows', 10000)),
            '--database-target', target, '--artifact', *spec.get('artifacts', [])]
        if spec.get('players'):
            command += ['--players', *spec['players']]
        preview = invoke(statistics.main, command)
        scope = preview['approval_scope']
        records = []
        for path in spec.get('artifacts', []):
            artifact = statistics.load_artifact(Path(path))
            # CLI validates the exact same unfiltered mapping and row scope.
            if spec.get('players'):
                athlete_ids = {str(m['athlete_id']) for m in mappings if m['player_id'] in spec['players']}
                artifact['responses'] = [r for r in artifact['responses'] if str(r['athlete_id']) in athlete_ids]
            records.extend(normalize_artifact(artifact, mappings, season=season,
                competition=spec.get('competition', 'Regular Season'), max_rows=spec.get('max_rows', 10000))['records'])
        details = coverage(records)
        rejected = preview['counts']['rejected']
        rejections = preview['sports'][sport.upper()]['rejected']
    return operation | details | dict(status='ready' if records and not rejected else 'skipped',
        reason=None if records and not rejected else 'No validated records or rejected rows; import prohibited',
        action=action, command=command, approval_scope=scope, rejected_game_logs=rejected,
        rejections=rejections,
        database_writes=len(records))


def quota_blocker(coverage_doc, plan):
    if not plan['requests']:
        return None
    quota = coverage_doc.get('quota', {})
    try:
        observed = datetime.fromisoformat(quota['observed_at'].replace('Z', '+00:00'))
        age = datetime.now(timezone.utc) - observed
        remaining = quota['remaining']
        if (type(remaining) is not int or remaining < 0 or not quota['evidence']
                or observed.tzinfo is None or not timedelta(0) <= age <= timedelta(hours=6)):
            raise ValueError('Invalid retained quota')
    except (KeyError, TypeError, ValueError):
        return 'Recent confirmed quota evidence required (at most six hours old); no discovery authorized'
    if remaining - plan['estimated_max_credits'] < plan['quota_reserve']:
        return 'Retained remaining quota cannot fund exact plan and reserve'
    return None


def build_plan(args):
    sports = select_sports(args.sports)
    if args.max_requests < 1 or args.max_credits < 0 or args.quota_reserve < 50:
        raise ValueError('Invalid ceilings; reserve must be at least 50')
    document = read(args.scope) if args.scope else {}
    operations = []
    if 'statistics' in args.include:
        for sport in sports:
            try:
                operations.append(statistics_plan(sport, document.get('statistics', {}).get(sport, {}), args.database_target))
            except Exception as exc:
                operations.append(dict(sport=sport, kind='statistics', status='failed',
                    source='nba_com_stats' if sport == 'nba' else SOURCES[sport.upper()],
                    season=document.get('statistics', {}).get(sport, {}).get('season', season_name(sport.upper())),
                    reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                    provider_requests=0, database_writes=0))
    requests = sum(o['provider_requests'] for o in operations)
    odds_plan = None
    blocker = None
    quota_evidence = None
    if 'odds' in args.include:
        retained = read(args.coverage) if args.coverage else {}
        if retained.get('database_target') not in (None, args.database_target):
            raise ValueError('Coverage database target differs from selected target')
        retained['database_target'] = args.database_target
        quota_evidence = retained.get('quota', {})
        odds_plan = odds.plan_refresh(retained, [SPORTS[s] for s in sports],
            max_credits=args.max_credits, max_requests=max(1, args.max_requests-requests))
        odds_plan['quota_reserve'] = args.quota_reserve
        # Quota evidence is bound into coverage_sha256; it is never fetched in preview.
        blocker = quota_blocker(retained, odds_plan)
        if odds_plan['requests'] and not args.database_target:
            blocker = 'Exact database target required'
        requests += odds_plan['planned_max_requests']
    if requests > args.max_requests:
        raise ValueError('Combined provider request ceiling exceeded')
    return dict(version=1, sports=sports, include=sorted(set(args.include)), database_target=args.database_target,
        run_directory=str(args.output_dir.resolve()),
        max_requests=args.max_requests, max_credits=args.max_credits, provider_request_upper_bound=requests,
        sportsbook_credit_upper_bound=odds_plan['estimated_max_credits'] if odds_plan else 0,
        allow_player_creation=False, allow_identity_repairs=False, statistics=operations,
        odds=odds_plan, retained_quota=quota_evidence, odds_execution_blocker=blocker)


def validate_database(target):
    if any(k in os.environ for k in ('PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGSERVICE','PGSERVICEFILE','PGOPTIONS')):
        raise ValueError('Remove libpq routing overrides')
    from app.config import settings
    from app.services.nba_statistics_workflow import database_target
    identity = database_target(settings.DATABASE_URL)
    if (settings.ENVIRONMENT != 'development' or settings.LIVE_REFRESH_ENABLED
            or target != f"{identity['host']}:{identity['port']}/{identity['database']}"):
        raise ValueError('Exact development target with live refresh disabled required')


def execute_statistics(operation, folder):
    sport = operation['sport']
    if operation['action'] == 'collect':
        plan = operation['collection_plan']
        if sport == 'nba':
            from scripts.collect_nba_statistics import collect, plan_digest
            Path(operation['output']).parent.mkdir(parents=True, exist_ok=True)
            artifact = collect(plan, approved_plan_sha256=plan_digest(plan), output=Path(operation['output']))
        else:
            from scripts.collect_nhl_statistics import collect, plan_digest
            artifact = collect(plan, approved_plan_sha256=plan_digest(plan), output=operation['output'])
        details = {}
        failures = list(artifact.get('failures', []))
        try:
            if sport == 'nba':
                from app.services.nba_statistics_workflow import prepare_batch
                batch = prepare_batch(plan['players'], artifact, season=plan['season'], competition=plan['competition'],
                    date_from=plan['date_from'], date_to=plan['date_to'], max_rows=operation['max_rows'])
                records = [r for p in batch['players'] for r in p['records']]
            else:
                batch = normalize_artifact(artifact, plan['players'], season=plan['season'],
                    competition=plan['competition'], max_rows=operation['max_rows'])
                failures.extend(batch['rejected'])
                records = batch['records']
            details = coverage(records, nba=sport == 'nba')
        except Exception as exc:
            failures.append(dict(reason='Offline validation: '+type(exc).__name__))
        return details | dict(status='partial' if failures else 'collected', artifact=operation['output'],
            actual_api_requests=artifact.get('request_count', 'unknown'), database_writes=0,
            failures=failures, note='Import requires a new artifact preview and approval')
    # This is the exact child scope embedded in the human-approved parent digest.
    approval = folder / f'{sport}-approved-import-scope.json'
    atomic_json(approval, operation['approval_scope'])
    if sport == 'nba':
        from scripts.import_nba_statistics import main
        result = invoke(main, operation['command'] + ['--execute', '--approval', str(approval)])
        counts = {k: sum(p[k] for p in result['players']) for k in ('added','updated','unchanged')}
        counts['new'] = counts.pop('added')
        counts['rejected'] = 0
    else:
        result = invoke(statistics.main, operation['command'] + ['--import-approved', str(approval)])
        counts = result['counts']
    return dict(status='imported', players_updated='unknown',
        **{k+'_game_logs': v for k,v in counts.items()},
        database_writes=counts['new']+counts['updated'], actual_api_requests=0)


def execute(plan, approved_digest, folder):
    if approved_digest != statistics.digest(plan):
        raise ValueError('Approval must match exact current execution-plan digest')
    ready = [o for o in plan['statistics'] if o['status'] == 'ready']
    if any(o['database_writes'] for o in ready) or (plan['odds'] and plan['odds']['requests'] and not plan['odds_execution_blocker']):
        validate_database(plan['database_target'])
    if folder.resolve() != Path(plan['run_directory']).resolve():
        raise ValueError('Run directory differs from approved plan')
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'execution-claim.json').open('x', encoding='utf-8') as handle:
        json.dump(dict(plan_sha256=approved_digest, note='Single attempt; interrupted runs require a new preview/approval'), handle)
    result = dict(mode='executed', plan_sha256=approved_digest, operations=[],
        actual_api_requests=0, credits_consumed=0, confirmed_credits_remaining='unknown')
    for operation in plan['statistics']:
        item = dict(statistics_last_observed='unknown', latest_completed_game_represented='unknown',
            players_updated='unknown', new_game_logs='unknown', updated_game_logs='unknown',
            unchanged_game_logs='unknown', rejected_game_logs='unknown', events_processed='unknown',
            offers_inserted_or_updated='unknown', actual_api_requests=0) | operation
        if item['status'] == 'ready':
            try:
                item.update(execute_statistics(operation, folder))
            except Exception as exc:
                item.update(status='failed', reason=type(exc).__name__, actual_api_requests='unknown', database_writes='unknown')
        result['operations'].append(item)
    if plan['odds']:
        if plan['odds_execution_blocker']:
            result['odds'] = dict(status='skipped', reason=plan['odds_execution_blocker'])
        else:
            try:
                # Existing executor retains per-sport transactions, event metadata checks,
                # equivalent-line identity, freshness policy and provider budget accounting.
                with redirect_stdout(io.StringIO()):
                    report = odds.execute(plan['odds'], odds.plan_digest(plan['odds']),
                        allow_player_changes=False, strict_scope=True)
                result['odds'] = report
                result['credits_consumed'] = report.get('credits_consumed', 'unknown' if plan['odds']['requests'] else 0)
                result['confirmed_credits_remaining'] = report.get('quota_remaining')
                if result['confirmed_credits_remaining'] is None:
                    result['confirmed_credits_remaining'] = 'unknown'
            except Exception as exc:
                result['odds'] = dict(status='failed', reason=type(exc).__name__)
                result.update(credits_consumed='unknown', confirmed_credits_remaining='unknown')
    totals = [o.get('actual_api_requests', 0) for o in result['operations']]
    odds_report = result.get('odds', {})
    totals.append(odds_report.get('provider_requests_consumed', 'unknown' if odds_report.get('status') == 'failed' else 0))
    result['actual_api_requests'] = sum(totals) if all(type(t) is int for t in totals) else 'unknown'
    for key, status in odds_report.get('sports', {}).items():
        result['operations'].append(dict(sport=next(s for s,k in SPORTS.items() if k == key), kind='odds',
            source='the_odds_api', season='unknown', statistics_last_observed='unknown',
            latest_completed_game_represented='unknown', players_updated='unknown',
            new_game_logs='unknown', updated_game_logs='unknown', unchanged_game_logs='unknown', rejected_game_logs='unknown',
            status=status.get('outcome', status.get('coverage', 'unknown')),
            events_processed=status.get('events_successfully_processed', 'unknown'),
            offers_inserted_or_updated=status.get('sportsbook_offers_saved', 'unknown'),
            failures=status.get('errors', []), skips=status.get('warnings', []),
            market_requests=status.get('market_requests_made', 'unknown'), actual_api_requests='unknown'))
    result['status'] = 'partial' if (any(o['status'] in {'failed','partial','unsupported'} for o in result['operations'])
        or odds_report.get('status') in {'failed','skipped','skipped_locked'}) else 'finished'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sports', nargs='+', choices=[*SPORTS, 'all'], required=True)
    parser.add_argument('--include', nargs='+', choices=['statistics','odds'], default=['statistics','odds'])
    parser.add_argument('--scope', type=Path, help='Local JSON statistics scopes, keyed by sport')
    parser.add_argument('--coverage', type=Path, help='Existing retained odds coverage plus quota evidence')
    parser.add_argument('--database-target', help='Exact host:port/database; never credentials')
    parser.add_argument('--max-requests', type=int, default=100)
    parser.add_argument('--max-credits', type=int, default=0)
    parser.add_argument('--quota-reserve', type=int, default=50)
    parser.add_argument('--output-dir', type=Path, default=RUNS / 'unified-refresh' / str(uuid4()))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--execute-approved', metavar='PLAN_SHA256', help='Explicit approval of displayed provider and database scope')
    args = parser.parse_args(argv)
    try:
        if not args.output_dir.resolve().is_relative_to(RUNS.resolve()):
            raise ValueError('Run summaries must stay under ignored backend/data/odds_runs')
        if (args.output_dir / 'execution-claim.json').exists():
            raise ValueError('Run already attempted; retain its summary and select a fresh output directory')
        plan = build_plan(args)
        digest = statistics.digest(plan)
        result = execute(plan, args.execute_approved, args.output_dir) if args.execute_approved else dict(
            mode='dry-run', plan=plan, plan_sha256=digest, actual_api_requests=0,
            database_writes=0, credits_consumed=0, confirmed_credits_remaining='unknown')
        args.output_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(args.output_dir / 'plan.json', plan)
        atomic_json(args.output_dir / 'summary.json', result)
        result['summary_file'] = str(args.output_dir / 'summary.json')
        print(json.dumps(result, indent=2, default=str))
        failed = any(o['status'] in {'failed','partial'} for o in result.get('operations', plan['statistics']))
        if result.get('odds', {}).get('status') == 'failed':
            failed = True
        if result.get('status') == 'partial':
            failed = True
        return 1 if failed else 0
    except Exception as exc:
        print(json.dumps(dict(status='rejected', reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
