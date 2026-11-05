"""Process coordination and atomic, credential-free ingestion diagnostics."""
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text

ODDS_LOCK_ID = 734901227


@contextmanager
def odds_ingestion_lock(engine, lock_id=ODDS_LOCK_ID):
    """Pin a dedicated PostgreSQL session across HTTP work AND all DB commits.

    Connection close alone returns sessions to a pool, so explicitly unlock;
    invalidate a broken session so the pool cannot retain an orphaned lock.
    Process termination closes the socket and PostgreSQL releases the lock.
    """
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Odds ingestion requires PostgreSQL advisory locking")
    with engine.connect() as connection:
        acquired = False
        try:
            acquired = bool(connection.execute(text("SELECT pg_try_advisory_lock(:key)"),
                                               {"key": lock_id}).scalar())
            connection.commit()
            yield acquired
        finally:
            if acquired:
                try:
                    connection.rollback()
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
                    connection.commit()
                except Exception:
                    connection.invalidate()
                    raise


def atomic_json(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class RequestBudget:
    """HTTP attempts and conservative maximum credit reservation are separate.

    Unknown response cost consumes the reservation. Reliable headers replace
    that estimate; missing remaining quota stays unknown. Retries count too.
    """
    def __init__(self, max_requests=100, max_credits=500, reserve=50):
        self.max_requests = max_requests
        self.max_credits = max_credits
        self.reserve = reserve
        self.requests = 0
        self.credits = 0
        self.remaining = None
        self.stopped = False
        self.reason = None

    def can_request(self, cost):
        if self.stopped:
            return False
        if (self.requests >= self.max_requests or self.credits + cost > self.max_credits
                or (self.remaining is not None and self.remaining - cost < self.reserve)):
            self.stopped, self.reason = True, "request_or_credit_budget"
            return False
        return True

    def claim(self, cost):
        if not self.can_request(cost):
            return False
        self.requests += 1
        self.credits += cost
        if self.remaining is not None:
            self.remaining -= cost
        return True

    def observe(self, headers, reserved, status_code):
        for key, attr in (("x-requests-last", "last"), ("x-requests-remaining", "remaining")):
            try:
                value = int(headers.get(key))
                if value < 0:
                    continue
            except (TypeError, ValueError):
                continue
            if attr == "last":
                self.credits += value - reserved
            else:
                self.remaining = value
        if status_code == 402 or (self.remaining is not None and self.remaining <= self.reserve):
            self.stopped, self.reason = True, "provider_quota"

    def report(self):
        return {"provider_requests_consumed": self.requests, "credits_accounted": self.credits,
                "quota_remaining": self.remaining, "request_limit": self.max_requests,
                "credit_limit": self.max_credits, "budget_stop_reason": self.reason}
