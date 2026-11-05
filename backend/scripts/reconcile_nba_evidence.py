"""Explicit OFFLINE fixture rehearsal; never a live ESPN ingestion command."""
import argparse
import json
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--sport", choices=["NBA"], required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--team-id", action="append", required=True)
    parser.add_argument("--request-budget", type=int, choices=[0], default=0,
                        help="Live transport is unimplemented; zero HTTP requests only")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--authorize-fixture-write", action="store_true")
    parser.add_argument("--expected-digest")
    parser.add_argument("--test-database-url", help="Explicit loopback proppulse_test_ database only")
    args = parser.parse_args(argv)
    # Override configured database routing before importing application modules.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ.update(DATABASE_URL="sqlite:///:memory:", LIVE_REFRESH_ENABLED="false",
                      THE_ODDS_API_KEY="", BALLDONTLIE_API_KEY="")
    try:
        if args.fixture.stat().st_size > 2_000_000:
            raise ValueError("Fixture exceeds 2 MB input bound")
        manifest = json.loads(args.fixture.read_text(encoding="utf-8"))
        from app.services.nba_evidence_service import reconcile_fixture
        scope = dict(sport=args.sport, start_date=args.start_date, end_date=args.end_date, team_ids=args.team_id)
        if not args.write:
            if args.test_database_url or args.authorize_fixture_write or args.expected_digest:
                raise ValueError("Dry-run is offline and accepts no database or write arguments")
            report = reconcile_fixture(None, manifest, **scope)
        else:
            if not args.authorize_fixture_write or not args.expected_digest or not args.test_database_url:
                raise ValueError("Write requires explicit fixture authorization, dry-run digest and test database")
            from sqlalchemy.engine import make_url
            target = make_url(args.test_database_url)
            if (target.get_backend_name() != "postgresql" or target.host not in {"127.0.0.1", "localhost"}
                    or not (target.database or "").startswith("proppulse_test_") or target.query):
                raise ValueError("Only explicit loopback disposable PostgreSQL targets are accepted")
            # libpq ambient routing must not override the validated explicit URL.
            for key in list(os.environ):
                if key.upper().startswith("PG"):
                    os.environ.pop(key)
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            engine = create_engine(target, connect_args={"connect_timeout": 3})
            try:
                with Session(engine) as db, db.begin():
                    report = reconcile_fixture(db, manifest, **scope, write=True, expected_digest=args.expected_digest)
            finally:
                engine.dispose()
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:
        # DB/JSON errors can include URLs or arbitrary file contents. Never echo them.
        print(json.dumps({"status": "rejected", "reason": "invalid_fixture_scope_authorization_or_test_database"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
