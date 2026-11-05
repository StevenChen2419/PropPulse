"""Preview one pinned Event/ten-prop operation; --execute also requires approval.

No provider calls or migrations. This script never accepts arbitrary manifests,
events, prop IDs or database URLs. Review docs/milestone-3c-bounded-linkage.md.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.services.verified_event_linkage import run_verified_linkage, validate_target_url, LinkageRejected
from app.services.verified_linkage_scope import APPROVAL_PHRASE, load_reviewed_files, ScopeRejected
from app.services.ingestion_control import atomic_json
from scripts.prepare_event_links import manifest_output, write_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Only after separate explicit operator authorization")
    parser.add_argument("--approve", help="Reviewed operator confirmation phrase; required with --execute")
    parser.add_argument("--expected-existing-event-id", help="Previously reviewed UUID; mandatory to reuse an existing Event")
    parser.add_argument("--report", type=Path, required=True,
                        help="New protected .json report under backend/data/odds_runs/verification; never overwritten")
    args = parser.parse_args(argv)
    engine = None
    report = None
    try:
        output = manifest_output(args.report)
        if args.execute and args.approve != APPROVAL_PHRASE:
            raise LinkageRejected("operator_approval_required")
        if settings.ENVIRONMENT != "development" or settings.LIVE_REFRESH_ENABLED:
            raise LinkageRejected("development_refresh_guard")
        validate_target_url(settings.DATABASE_URL)
        load_reviewed_files()  # no connection if pinned files fail
        # Reserve a new report before any database work. A crash leaves a visible
        # started report; it must never be interpreted as proof of rollback.
        write_manifest(output, {"status": "started", "execution_requested": args.execute,
                                "transaction_outcome": "not_yet_reported"})
        engine = create_engine(settings.DATABASE_URL, poolclass=NullPool, pool_pre_ping=True,
            connect_args={"connect_timeout": 5,
                          "options": "-c default_transaction_read_only=on -c application_name=proppulse_verified_linkage"})
        report = run_verified_linkage(engine, execute=args.execute, approval=args.approve,
                                     expected_existing_event_id=args.expected_existing_event_id)
        atomic_json(output, report)
        print(json.dumps({key: report[key] for key in ("mode", "status", "transaction_outcome", "committed", "rejections")}, indent=2))
        return 0 if report["status"] == "completed" else 1
    except Exception as error:
        # No driver exception text, SQL, connection URLs or report payloads.
        reason = str(error) if isinstance(error, (LinkageRejected, ScopeRejected)) else type(error).__name__
        print("Bounded linkage failed: " + reason, file=sys.stderr)
        if report is not None:
            print(json.dumps({"report_persistence_failed": True,
                **{key: report.get(key) for key in ("transaction_outcome", "committed", "event_id")}}),
                file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
