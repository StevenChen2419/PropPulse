"""Import a reviewed, previously collected NBA artifact; dry-run by default.

No provider HTTP, application startup, table creation, or migrations are invoked.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def _load(path):
    raw = path.read_bytes()
    if len(raw) > 10_000_000:
        raise ValueError("Input exceeds the 10 MB bound")
    return json.loads(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--season", required=True, choices=["2025-26", "2026-27"])
    parser.add_argument("--competition", required=True, choices=["Regular Season"])
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--player", action="append", dest="player_ids")
    parser.add_argument("--max-rows", type=int, default=1000)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval", type=Path,
                        help="Explicitly approved scope JSON, matching dry-run approval_scope")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    engine = None
    try:
        # libpq environment variables can silently redirect the approved target.
        if any(key in os.environ for key in ("PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")):
            raise ValueError("Remove libpq routing overrides before importing")
        from app.config import settings
        from sqlalchemy import create_engine
        from app.services.nba_statistics_workflow import database_target, prepare_batch, run_import
        if settings.ENVIRONMENT != "development" or settings.LIVE_REFRESH_ENABLED:
            raise ValueError("Import requires development environment with live refresh disabled")
        target = database_target(settings.DATABASE_URL)
        mappings, mapping_digest = _load(args.mapping)
        artifact, artifact_digest = _load(args.artifact)
        batch = prepare_batch(mappings, artifact, season=args.season,
            competition=args.competition, date_from=args.date_from, date_to=args.date_to,
            player_ids=args.player_ids, max_rows=args.max_rows)
        approval_scope = dict(database_target=target, mapping_sha256=mapping_digest,
            artifact_sha256=artifact_digest, season=args.season, competition=args.competition,
            date_from=args.date_from, date_to=args.date_to,
            player_ids=sorted(player["player_id"] for player in batch["players"]),
            max_rows=args.max_rows)
        if args.execute:
            if args.approval is None or _load(args.approval)[0] != approval_scope:
                raise ValueError("Execute requires explicit approval JSON matching the exact dry-run approval_scope")
        elif args.approval is not None:
            raise ValueError("Approval is accepted only with explicit --execute")
        engine = create_engine(settings.DATABASE_URL, connect_args={"connect_timeout": 3}, pool_pre_ping=True)
        result = run_import(engine, batch, execute=args.execute)
        result["approval_scope"] = approval_scope
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        # SQLAlchemy errors can include connection strings or SQL parameters.
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__ + ": import failed; transaction rolled back"
        print(json.dumps({"error": message}), file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
