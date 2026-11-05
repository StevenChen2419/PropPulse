"""Plan-only by default; separately authorized, bounded NBA contract collection."""
import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", choices=["NBA"], required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--team-id", action="append", required=True)
    parser.add_argument("--game-id", action="append", required=True)
    parser.add_argument("--endpoint", action="append", choices=["teams", "roster", "scoreboard", "summary"], required=True)
    parser.add_argument("--request-budget", type=int, required=True)
    parser.add_argument("--min-delay-seconds", type=float, required=True)
    parser.add_argument("--max-retries", type=int, required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--redaction-policy", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorization-phrase")
    parser.add_argument("--reviewed-plan-sha256")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services.espn_contract_collection import CollectionRejected, build_collection_plan, execute_collection
    try:
        plan = build_collection_plan(start_date=args.start_date, end_date=args.end_date,
            team_ids=args.team_id, game_ids=args.game_id, endpoints=args.endpoint,
            request_budget=args.request_budget, min_delay_seconds=args.min_delay_seconds,
            max_retries=args.max_retries, output_dir=args.outdir, redaction_policy=args.redaction_policy)
        if args.execute:
            result = execute_collection(plan, authorization=args.authorization_phrase,
                                        reviewed_plan_sha256=args.reviewed_plan_sha256)
        else:
            if args.authorization_phrase or args.reviewed_plan_sha256:
                raise CollectionRejected("execution_flags_require_explicit_execute")
            result = plan
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result.get("status", "completed") == "completed" else 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "reason": "collection_cancelled"}))
        return 130
    except SystemExit:
        print(json.dumps({"status": "interrupted", "reason": "collection_cancelled"}))
        return 1
    except Exception:
        # Unexpected transport/filesystem failures may include sensitive text.
        print(json.dumps({"status": "rejected", "reason": "invalid_scope_plan_authorization_or_output"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
