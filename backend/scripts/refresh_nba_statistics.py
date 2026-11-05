"""Manual NBA refresh: offline plan, approved collection, then separate import.

No HTTP or database connection is made by the default dry-run. An artifact dry-run
uses the existing PostgreSQL-enforced read-only importer. Human approval remains
required separately for the exact collection digest and exact import scope.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import collect_nba_statistics as collector
from scripts import import_nba_statistics as importer

BACKEND = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', required=True, choices=['2025-26', '2026-27'])
    parser.add_argument('--competition', default='Regular Season', choices=['Regular Season'])
    parser.add_argument('--from-date', required=True)
    parser.add_argument('--to-date', required=True)
    players = parser.add_mutually_exclusive_group(required=True)
    players.add_argument('--players', nargs='+', help='Exact local Player UUIDs from the reviewed mapping')
    players.add_argument('--all-verified', action='store_true')
    parser.add_argument('--mapping', type=Path, default=BACKEND / 'data/nba_player_mappings.json')
    parser.add_argument('--output-dir', type=Path, help='Ignored local artifact directory; use a fresh directory per collection')
    parser.add_argument('--max-rows', type=int, default=1000)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Default: plan, or read-only preview when --artifact is supplied')
    mode.add_argument('--collect-approved', metavar='PLAN_SHA256', help='Execute only the separately approved collection plan')
    mode.add_argument('--import-approved', type=Path, metavar='APPROVAL_JSON', help='Execute only the separately approved import scope')
    parser.add_argument('--artifact', type=Path, help='Previously collected artifact; never triggers provider HTTP')
    args = parser.parse_args(argv)
    try:
        if args.collect_approved and args.artifact:
            raise ValueError('Collection and artifact import are separate steps')
        if args.import_approved and not args.artifact:
            raise ValueError('--import-approved requires --artifact')
        if not 1 <= args.max_rows <= 10000:
            raise ValueError('--max-rows must be between 1 and 10000')
        first, last = date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)
        if first > last:
            raise ValueError('From date must be on or before to date')
        mappings, mapping_digest = importer._load(args.mapping)
        # Validate selection even when the season has not started. No name matching.
        selected = set(args.players or [])
        if selected - {entry['player_id'] for entry in mappings}:
            raise ValueError('Unknown selected player UUID')
        plan = collector.build_plan(mappings, season=args.season, competition=args.competition,
            date_from=args.from_date, date_to=args.to_date, player_ids=args.players)
        if plan['status'] == 'no_games_yet':
            if args.artifact or args.import_approved or args.collect_approved:
                raise ValueError('No completed 2026-27 Regular Season Eastern dates are available for this range')
            print(json.dumps(dict(status='no_games_yet', season=args.season,
                competition=args.competition, provider_requests=0, database_writes=0,
                plan=plan, plan_sha256=collector.plan_digest(plan),
                message='2026-27 Regular Season begins October 20, 2026. Select completed Eastern dates after games finish; no statistics were fabricated.')))
            return 0
        folder = args.output_dir or BACKEND / 'data/odds_runs/nba-refresh' / f'{args.season}_{args.from_date}_{args.to_date}'
        if not args.artifact:
            if not args.collect_approved:
                print(json.dumps(dict(status='collection_approval_required', mode='dry-run',
                    plan=plan, plan_sha256=collector.plan_digest(plan), mapping_sha256=mapping_digest,
                    artifact_location=str(folder / 'collected-responses.json'),
                    import_status='not_started'), indent=2))
                return 0
            # Validate approval before creating any artifacts.
            if args.collect_approved != collector.plan_digest(plan):
                raise ValueError('Approval must match the exact displayed plan digest')
            folder.mkdir(parents=True, exist_ok=True)
            output = folder / 'collected-responses.json'
            artifact = collector.collect(plan, approved_plan_sha256=args.collect_approved, output=output)
            if artifact.get('failures'):
                print(json.dumps(dict(status='collection_failed', artifact=str(output),
                    request_count=artifact['request_count'], failures=artifact['failures'],
                    import_status='not_started; no provider fallback or access bypass')))
                return 1
            # Reuse normalizer and all identity/scope guards without opening a DB.
            from app.services.nba_statistics_workflow import prepare_batch
            batch = prepare_batch(mappings, artifact, season=args.season, competition=args.competition,
                date_from=args.from_date, date_to=args.to_date, player_ids=args.players, max_rows=args.max_rows)
            print(json.dumps(dict(status='collected_and_validated', artifact=str(output),
                artifact_sha256=importer._load(output)[1], request_count=artifact['request_count'],
                responses=len(artifact['responses']), normalized_rows=batch['total_records'],
                import_status='not_started; rerun with --artifact for read-only preview'), indent=2))
            return 0
        command = ['--mapping', str(args.mapping), '--artifact', str(args.artifact),
            '--season', args.season, '--competition', args.competition,
            '--date-from', args.from_date, '--date-to', args.to_date, '--max-rows', str(args.max_rows)]
        for entry in plan['players']:
            command += ['--player', entry['player_id']]
        if args.import_approved:
            command += ['--execute', '--approval', str(args.import_approved)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = importer.main(command)
        if code:
            print(stderr.getvalue().strip() or stdout.getvalue().strip()
                  or json.dumps(dict(status='rejected', message='Import stopped before a successful preview or execution')))
            return code
        result = json.loads(stdout.getvalue())
        result['totals'] = {key: sum(player[key] for player in result['players'])
                            for key in ('added', 'updated', 'unchanged', 'records')}
        result['totals']['rejected'] = 0  # Any rejected batch fails closed, never partially imports.
        if not args.import_approved:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'import-preview.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            approval = folder / 'proposed-import-approval.json'
            approval.write_text(json.dumps(result['approval_scope'], indent=2), encoding='utf-8')
            result['proposed_approval_file'] = str(approval)
            result['status'] = 'import_approval_required'
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status='rejected', reason=str(exc) if type(exc) is ValueError else type(exc).__name__,
            message='Batch stopped. Existing import transaction guards remain in force; collected artifacts are retained.')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
