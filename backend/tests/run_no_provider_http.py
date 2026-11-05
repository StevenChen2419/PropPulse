"""Run unittest discovery while blocking external HTTP (ASGI TestClient is allowed).

Usage from backend: python tests/run_no_provider_http.py [discovery-pattern]
PostgreSQL suites opt in only via PROPPULSE_TEST_POSTGRES_URL and their existing
disposable-database/random-schema guards. No application lifespan is started here.
"""
import http.client
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx


def main():
    backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(backend / "tests"))
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("External HTTP is forbidden during backend verification")

    async def forbidden_async(*args, **kwargs):
        return forbidden()

    with patch.object(httpx.HTTPTransport, "handle_request", forbidden), \
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_async), \
            patch.object(http.client.HTTPConnection, "connect", forbidden):
        suite = unittest.defaultTestLoader.discover(str(backend / "tests"),
            pattern=sys.argv[1] if len(sys.argv) > 1 else "test*.py")
        def tests(items):
            for item in items:
                if isinstance(item, unittest.TestSuite):
                    yield from tests(item)
                else:
                    yield item
        # Real opt-in fixtures use *PostgresTests classes. Module/method names
        # also mention PostgreSQL in mocked target/read-only guard tests.
        postgres = sum(type(test).__name__.endswith("PostgresTests") for test in tests(suite))
        print(f"Discovered PostgreSQL scenarios: {postgres}", flush=True)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"External HTTP transport attempts: {len(attempts)}", flush=True)
    return 0 if result.wasSuccessful() and not attempts else 1


if __name__ == "__main__":
    sys.exit(main())
