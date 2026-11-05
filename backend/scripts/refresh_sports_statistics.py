"""Offline multi-sport artifact preview; exact separate approval for DB imports."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.sports_statistics import SOURCES, normalize_artifact, season_name, import_records


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def load_artifact(path):
    """Read retained JSON or published CSV via an adjacent descriptor; no HTTP.

    CSV assets are season-wide. Select exact athlete + competition rows before
    normalization; team rows and unselected athletes are never imported.
    """
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError('Artifact exceeds 50 MiB')
    artifact = json.loads(path.read_text(encoding='utf-8'))
    for response in artifact['responses']:
        if 'payload_file' not in response:
            continue
        if 'payload' in response:
            raise ValueError('Choose payload or payload_file, not both')
        payload_path = (path.parent / response['payload_file']).resolve()
        if not payload_path.is_relative_to(path.parent.resolve()) or payload_path.stat().st_size > 50 * 1024 * 1024:
            raise ValueError('Payload must be adjacent and at most 50 MiB')
        response['payload_file_sha256'] = hashlib.sha256(payload_path.read_bytes()).hexdigest()
        if payload_path.suffix.lower() == '.csv':
            if artifact['sport'] not in {'WNBA','NFL'}:
                raise ValueError('CSV assets supported for WNBA/NFL only')
            with payload_path.open(encoding='utf-8-sig', newline='') as handle:
                rows = [{k: v if v != '' else None for k,v in row.items()} for row in csv.DictReader(handle)]
            athlete = str(response['athlete_id'])
            if artifact['sport'] == 'WNBA':
                season_id = ('2' if artifact['competition'] == 'Regular Season' else '4') + artifact['season']
                selected = [r for r in rows if str(r.get('player_id')) == athlete and str(r.get('season_id')) == season_id]
            else:
                competition = 'REG' if artifact['competition'] == 'Regular Season' else 'POST'
                selected = [r for r in rows if str(r.get('player_id')) == athlete and str(r.get('season')) == artifact['season'] and r.get('season_type') == competition]
            response['payload'] = selected
            response['asset_rows'] = len(rows)
            response['selected_rows'] = len(selected)
        elif payload_path.suffix.lower() == '.json':
            response['payload'] = json.loads(payload_path.read_text(encoding='utf-8'))
        else:
            raise ValueError('Use published CSV or JSON; no parquet dependency required')
    return artifact


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sports', nargs='+', required=True, choices=['nba', 'wnba', 'nhl', 'nfl', 'mlb'])
    parser.add_argument('--season', default='current', help='Year, NHL/NBA YYYY-YY, or current per sport')
    parser.add_argument('--competition', choices=['Regular Season', 'Playoffs'], default='Regular Season')
    parser.add_argument('--players', nargs='+', help='Exact reviewed local UUIDs; default all reviewed mappings')
    parser.add_argument('--mapping', type=Path)
    parser.add_argument('--artifact', type=Path, nargs='*', default=[])
    parser.add_argument('--max-rows', type=int, default=10000)
    parser.add_argument('--database-target', help='Exact host:port/database for separately approved import; no credentials')
    parser.add_argument('--preview-database', action='store_true', help='Optional PostgreSQL-enforced read-only comparison for new/updated/unchanged counts')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--import-approved', type=Path, help='Exact scope JSON returned by dry-run, separately approved')
    parser.add_argument('--nba-args', nargs=argparse.REMAINDER, help='Delegate remaining arguments to existing NBA refresh command')
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.max_rows <= 10000:
            raise ValueError('max-rows must be 1..10000')
        sports = list(dict.fromkeys(s.upper() for s in args.sports))
        if 'NBA' in sports:
            if sports != ['NBA'] or not args.nba_args or args.import_approved:
                raise ValueError('NBA reuses refresh_nba_statistics.py: select --sports nba --nba-args <existing arguments> separately')
            from scripts.refresh_nba_statistics import main as nba_main
            return nba_main(args.nba_args)
        mappings = json.loads(args.mapping.read_text(encoding='utf-8')) if args.mapping else []
        from app.services.sports_statistics import reviewed_mappings, validate_season
        reviewed_mappings(mappings)
        if args.players and set(args.players) - {m['player_id'] for m in mappings if m['sport'] in sports}:
            raise ValueError('Selected player is not reviewed in selected sports')
        selected = [m for m in mappings if m['sport'] in sports and (not args.players or m['player_id'] in args.players)]
        artifacts = [load_artifact(path) for path in args.artifact]
        reports, records = {}, []
        for sport in sports:
            season = validate_season(sport, season_name(sport) if args.season == 'current' else args.season)
            batches = [a for a in artifacts if a.get('sport') == sport]
            report = dict(source=SOURCES[sport], season=season, records=0, rejected=[], status='artifact_required')
            for artifact in batches:
                # Preserve original file digest in approval, but normalize selected reviewed athletes only.
                filtered = {**artifact, 'responses': [r for r in artifact['responses'] if (not args.players or str(r['athlete_id']) in
                    {str(m['athlete_id']) for m in selected if m['sport'] == sport})]}
                batch = normalize_artifact(filtered, selected, season=season, competition=args.competition, max_rows=args.max_rows)
                records.extend(batch['records'])
                report['records'] += len(batch['records'])
                report['rejected'].extend(batch['rejected'])
                report['status'] = 'validated_offline'
            reports[sport] = report
        if any(a.get('sport') not in sports for a in artifacts):
            raise ValueError('Artifact outside selected sports')
        if len(records) > args.max_rows:
            raise ValueError('Combined record limit exceeded')
        keys = [(r['player_id'], r['external_game_id']) for r in records]
        if len(keys) != len(set(keys)):
            raise ValueError('Overlapping artifacts: provide one authoritative observation per game')
        scope = dict(operation='import_sports_statistics', mapping_sha256=digest(selected),
            artifact_sha256=[digest(a) for a in artifacts], records_sha256=digest(records), sports=sports,
            players=sorted({r['player_id'] for r in records}), competition=args.competition,
            max_rows=args.max_rows, records=len(records), database_target=args.database_target)
        counts = dict(new=None, updated=None, unchanged=None, rejected=sum(len(r['rejected']) for r in reports.values()))
        if args.preview_database and args.import_approved:
            raise ValueError('Preview and import are separate operations')
        if args.preview_database or args.import_approved:
            from app.config import settings
            from sqlalchemy.engine import make_url
            target = make_url(settings.DATABASE_URL)
            if not args.database_target or target.get_backend_name() != 'postgresql' or args.database_target != f'{target.host}:{target.port or 5432}/{target.database}':
                raise ValueError('Name the exact configured PostgreSQL database target')
        if args.preview_database:
            from app.database import SessionLocal
            from sqlalchemy import text
            with SessionLocal() as db, db.begin():
                db.execute(text('SET TRANSACTION READ ONLY'))
                counts = import_records(db, records, write=False)
        if args.import_approved:
            if not records or counts['rejected'] or json.loads(args.import_approved.read_text(encoding='utf-8')) != scope:
                raise ValueError('Import approval must match exact validated scope with no rejected rows')
            # Database identity is explicit and credentials are never printed.
            from app.database import SessionLocal
            with SessionLocal() as db:
                with db.begin():
                    counts = import_records(db, records)
        print(json.dumps(dict(mode='imported' if args.import_approved else 'dry-run', sports=reports,
            counts=counts, database_writes=len(records) if args.import_approved else 0,
            provider_requests=0, approval_scope=scope,
            note='Offline preview validates source rows only; --preview-database provides PostgreSQL read-only comparison counts.'), indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps(dict(status='rejected', reason=str(exc))))
        return 1
    except Exception as exc:
        print(json.dumps(dict(status='failed', reason=type(exc).__name__, message='Import transaction rolled back; inspect local configuration without exposing credentials.')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
