"""Periodic provider ingestion, isolated from HTTP requests and serialized across workers."""
import json
import os
from uuid import uuid4
from app.services.ingestion_control import atomic_json, odds_ingestion_lock
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.config import settings
from app.database import engine

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "data" / "live_refresh_status.json"
LOCK_ID = 734901226
logger = logging.getLogger(__name__)


def read_refresh_status():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def provider_result(name, process_result):
    if isinstance(process_result, dict):
        return process_result["status"]
    if process_result != "completed":
        return process_result
    filename = "game_log_ingestion_status.json" if name == "history" else "odds_ingestion_status.json"
    try:
        status = json.loads((ROOT / "data" / filename).read_text(encoding="utf-8"))
        if name == "history":
            return status.get("status", "unknown")
        if status.get("run_id"):
            return status.get("status", "unknown")
        sports = list((status.get("sports") or {}).values())
        if any(s.get("market_requests_failed", 0) or s.get("availability") in ("unavailable", "last_known")
               for s in sports):
            return "partial" if any(s.get("availability") == "live" for s in sports) else "unavailable"
        return "completed"
    except (OSError, ValueError, TypeError):
        return "unknown"


def due(job, interval, now):
    if job.get("status") == "interrupted":
        return True
    return now - job.get("finished_epoch", 0) >= interval


def odds_retry_interval(interval):
    """Back off for credentials/quota failures, while allowing later recovery."""
    try:
        status = json.loads((ROOT / "data" / "odds_ingestion_status.json").read_text(encoding="utf-8"))
        sports = list((status.get("sports") or {}).values())
        quotas = [int(s["quota_requests_remaining"]) for s in sports
                  if s.get("quota_requests_remaining") is not None]
        if (quotas and min(quotas) <= settings.ODDS_MIN_REMAINING_CREDITS) or any(
            s.get("provider_http_status") in (401, 403) for s in sports
        ):
            return max(interval, 21600)
    except (OSError, ValueError, TypeError):
        pass
    return interval


class LiveRefresh:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if settings.LIVE_REFRESH_ENABLED:
            self.thread = threading.Thread(target=self.run, name="live-provider-refresh", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def save(self, state):
        atomic_json(STATE_PATH, state)

    def execute(self, script, args):
        # Keep provider diagnostics in a local log; do not expose credentials via /health.
        log_path = ROOT / "data" / (Path(script).stem + ".log")
        run_id = str(uuid4())
        child_env = {**os.environ, "PROPPULSE_ODDS_RUN_ID": run_id}
        with log_path.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "scripts" / script), *args],
                cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, env=child_env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + 1800
            while process.poll() is None:
                if self.stop_event.wait(1) or time.monotonic() >= deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    return "interrupted"
            if script == "fetch_odds.py":
                try:
                    status = json.loads((ROOT / "data" / "odds_runs" / (run_id + ".json")).read_text(encoding="utf-8"))
                    if status.get("run_id") == run_id and status.get("status") != "started":
                        return {"status": status["status"], "run_id": run_id}
                except (OSError, ValueError, TypeError):
                    pass
                return "failed"
            return "completed" if process.returncode == 0 else "failed"

    def refresh(self):
        # Scheduler ownership is separate from the child's shared dataset lock.
        with odds_ingestion_lock(engine, LOCK_ID) as acquired:
            if not acquired:
                return
            state = read_refresh_status()
            jobs = (
                ("odds", "fetch_odds.py", [], odds_retry_interval(settings.ODDS_REFRESH_SECONDS)),
                ("history", "fetch_player_game_logs.py", ["--sport", "all"], settings.HISTORY_REFRESH_SECONDS),
            )
            for name, script, args, interval in jobs:
                if self.stop_event.is_set():
                    break
                previous = state.get(name, {})
                if not due(previous, interval, time.time()):
                    continue
                if name == "odds" and not settings.the_odds_api_key:
                    state[name] = {"status": "missing_api_key", "finished_epoch": time.time()}
                    self.save(state)
                    continue
                state[name] = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
                self.save(state)
                result = provider_result(name, self.execute(script, args))
                state[name].update(status=result, finished_epoch=time.time(),
                                   finished_at=datetime.now(timezone.utc).isoformat())
                self.save(state)

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.refresh()
            except Exception:
                # Transport exceptions can embed credential-bearing provider URLs.
                logger.error("Automatic provider refresh failed; inspect protected ingestion status")
            self.stop_event.wait(30)
