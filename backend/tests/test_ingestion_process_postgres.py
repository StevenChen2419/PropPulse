"""Opt-in worker-process locking checks against a disposable PostgreSQL database."""
import os
import queue
import subprocess
import sys
import threading
import time
import unittest

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.services.ingestion_control import odds_ingestion_lock

TEST_URL = os.environ.get("PROPPULSE_TEST_POSTGRES_URL")
WORKER = """
import os
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from app.services.ingestion_control import odds_ingestion_lock
engine = create_engine(os.environ['PROPPULSE_TEST_POSTGRES_URL'], poolclass=NullPool)
with odds_ingestion_lock(engine) as acquired:
    print('acquired' if acquired else 'contended', flush=True)
    input()
engine.dispose()
"""


@unittest.skipUnless(TEST_URL, "PROPPULSE_TEST_POSTGRES_URL is unset; no PostgreSQL connection attempted")
class IngestionProcessPostgresTests(unittest.TestCase):
    def setUp(self):
        target = make_url(TEST_URL)
        if target.get_backend_name() != "postgresql" or not (target.database or "").startswith("proppulse_test_"):
            raise RuntimeError("Worker tests require an explicit proppulse_test_ database")
        self.engine = create_engine(target, poolclass=NullPool)
        self.addCleanup(self.engine.dispose)

    def start_worker(self):
        child = subprocess.Popen([sys.executable, "-c", WORKER], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.addCleanup(self.close_worker, child)
        messages = queue.Queue()
        threading.Thread(target=lambda: messages.put(child.stdout.readline().strip()), daemon=True).start()
        try:
            first = messages.get(timeout=15)
        except queue.Empty:
            self.fail("Lock worker did not report readiness within 15 seconds")
        self.assertEqual(first, "acquired", "Lock worker failed to acquire the isolated dataset lock")
        return child

    @staticmethod
    def close_worker(child):
        if child.poll() is None:
            child.terminate()
        try:
            child.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate(timeout=5)

    def assert_eventually_available(self):
        deadline = time.monotonic() + 5
        while True:
            with odds_ingestion_lock(self.engine) as acquired:
                if acquired:
                    return
            if time.monotonic() >= deadline:
                self.fail("PostgreSQL retained the terminated worker's advisory lock")
            time.sleep(0.05)

    def test_other_process_blocks_competitor_then_releases_on_success(self):
        child = self.start_worker()
        with odds_ingestion_lock(self.engine) as acquired:
            self.assertFalse(acquired)
        child.communicate(input="\n", timeout=15)
        self.assertEqual(child.returncode, 0)
        self.assert_eventually_available()

    def test_terminated_process_releases_session_lock(self):
        child = self.start_worker()
        with odds_ingestion_lock(self.engine) as acquired:
            self.assertFalse(acquired)
        child.terminate()
        child.communicate(timeout=15)
        self.assert_eventually_available()


if __name__ == "__main__":
    unittest.main()
