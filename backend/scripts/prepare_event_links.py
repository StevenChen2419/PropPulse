"""Prepare a dry-run linkage manifest from an explicit operator-trusted report.

Uses a PostgreSQL read-only transaction and performs no Event/prop writes. There
is no execute option. Output must be a new JSON file under the gitignored
backend/data/odds_runs/verification directory. On POSIX newly created directories
and files request owner-only permissions. Windows files inherit the directory's
ACL: the operator must protect the local workspace/report directory with an
appropriate Windows ACL before use. A manifest never authorizes DB writes.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine

from app.config import settings
from app.services.event_backfill import read_prop_identities
from app.services.event_link_manifest import build_event_link_manifest


MANIFEST_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "odds_runs" / "verification"


def manifest_output(path):
    """Resolve symlinks before enforcing the protected output subtree."""
    root = MANIFEST_DIRECTORY.resolve()
    target = Path(path).resolve()
    if not target.is_relative_to(root) or target == root or target.suffix.lower() != ".json":
        raise ValueError("manifest_output_outside_protected_directory")
    if target.exists():
        raise ValueError("manifest_output_already_exists")
    return target


def write_manifest(path, manifest):
    target = manifest_output(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Recheck after directory creation, then use exclusive creation: no overwrite.
    target = manifest_output(target)
    payload = (json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained-report", type=Path, required=True,
                        help="Explicit operator-trusted controlled-smoke report; no automatic discovery")
    parser.add_argument("--output", type=Path, required=True,
                        help="New .json path under backend/data/odds_runs/verification")
    parser.add_argument("--target-event-id", help="Optional existing Event UUID for idempotent dry-run validation")
    parser.add_argument("--max-candidates", type=int, default=10, help="Conservative scope limit, 1 to 100")
    args = parser.parse_args(argv)
    engine = None
    try:
        output = manifest_output(args.output)
        source = args.retained_report.resolve(strict=True)
        if source.stat().st_size > 1000000:
            raise ValueError("retained_report_size_bound")
        trusted_report = json.loads(source.read_text(encoding="utf-8"))
        # Validate evidence and arguments before even constructing a DB engine.
        build_event_link_manifest([], trusted_report, evidence_source=str(source),
                                  target_event_id=args.target_event_id, max_candidates=args.max_candidates)
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True,
                               connect_args={"connect_timeout": 5})
        rows = read_prop_identities(engine)
        manifest = build_event_link_manifest(rows, trusted_report, evidence_source=str(source),
                                             target_event_id=args.target_event_id,
                                             max_candidates=args.max_candidates)
        write_manifest(output, manifest)
        print(f"Dry-run manifest prepared: {len(manifest['candidates'])} candidates; "
              f"{len(manifest['rejected'])} rejected. No database writes performed.")
        return 0
    except Exception:
        # Drivers/OS errors can contain credentials, SQL, local UUIDs or paths.
        print("Dry-run manifest preparation failed; check trusted evidence, protected output path, "
              "scope bounds, and read-only database availability.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
