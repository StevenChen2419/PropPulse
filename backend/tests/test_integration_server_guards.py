"""No-connection guards for the disposable browser integration harness."""
from pathlib import Path
import subprocess
import sys
import unittest

from integration_server import integration_target


class IntegrationServerGuardTests(unittest.TestCase):
    def test_loopback_disposable_target_accepted(self):
        target = integration_target("postgresql://postgres@127.0.0.1:59433/proppulse_test_review")
        self.assertEqual(target.database, "proppulse_test_review")

    def test_non_disposable_or_remote_targets_rejected(self):
        for value in ("", "not-a-url", "sqlite:///proppulse_test_review",
                      "postgresql://localhost/proppulse", "postgresql://remote/proppulse_test_review"):
            with self.subTest(target=value), self.assertRaises(RuntimeError):
                integration_target(value)

    def test_query_overrides_rejected_before_connection(self):
        for query in ("host=remote", "host=/tmp", "dbname=proppulse", "service=production",
                      "options=-csearch_path%3Dpublic", "host=127.0.0.1&dbname=proppulse"):
            with self.subTest(query=query), self.assertRaises(RuntimeError):
                integration_target("postgresql://127.0.0.1/proppulse_test_review?" + query)

    def test_import_is_inert_and_production_has_no_test_routes(self):
        # Separate interpreter prevents fixture settings leaking into the suite.
        code = """
import os,sys
from unittest.mock import patch
sys.path.insert(0, 'tests')
os.environ.update(DATABASE_URL='postgresql://unused@127.0.0.1:1/proppulse_test_inert',
                  LIVE_REFRESH_ENABLED='false', THE_ODDS_API_KEY='', BALLDONTLIE_API_KEY='')
from sqlalchemy.engine import Engine
with patch.object(Engine, 'connect', side_effect=AssertionError('No DB connection permitted')):
    import integration_server
    assert 'app.main' not in sys.modules
    from app.main import app
    assert not any(route.path.startswith('/__test__') for route in app.routes)
print('inert import and production routes verified')
"""
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("inert import and production routes verified", result.stdout)


if __name__ == "__main__":
    unittest.main()
