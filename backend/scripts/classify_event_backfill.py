"""Print an event-backfill classification to stdout; no DB or filesystem writes.

Run from backend: .\\venv\\Scripts\\python.exe scripts/classify_event_backfill.py
Optional --retained-report paths must be operator-trusted local smoke reports.
No provider network requests, ingestion imports, models, lifespan or migrations.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from app.config import settings
from app.services.event_backfill import classify_events, read_prop_identities, retained_event


def load_metadata(paths):
    metadata, rejected = [], 0
    for path in paths:
        try:
            path = Path(path)
            if path.stat().st_size > 1000000:
                raise ValueError("oversized metadata report")
            item = retained_event(json.loads(path.read_text(encoding="utf-8")))
            if item is None:
                rejected += 1
            else:
                metadata.append(item)
        except (OSError, ValueError, TypeError):
            rejected += 1
    return metadata, rejected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained-report", action="append", type=Path,
                        help="Trusted controlled-smoke JSON; repeatable. Default: local odds_runs/*.json")
    parser.add_argument("--sample-limit", type=int, default=30)
    args = parser.parse_args(argv)
    paths = args.retained_report
    if paths is None:
        paths = sorted((Path(__file__).resolve().parents[1] / "data" / "odds_runs").glob("*.json"))
    metadata, rejected = load_metadata(paths)
    engine = None
    try:
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True,
                               connect_args={"connect_timeout": 5})
        report = classify_events(read_prop_identities(engine), metadata, args.sample_limit)
        report["metadata_reports"] = {"accepted": len(metadata), "ignored_or_invalid": rejected}
        print(json.dumps(report, indent=2))
        return 0
    except Exception:
        # Driver exceptions can contain credentials, SQL and connection addresses.
        print("Read-only classification failed; check database availability, schema, and argument bounds.", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
