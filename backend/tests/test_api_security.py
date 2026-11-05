"""Isolated request/abuse boundaries; no database, provider or app lifespan."""
import asyncio
import unittest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.config import Settings
from app.services.api_security import APISecurityMiddleware, WindowLimiter


class APISecurityTests(unittest.TestCase):
    def setUp(self):
        self.clock = [0.0]
        self.limiter = WindowLimiter(clock=lambda: self.clock[0])
        self.app = FastAPI()
        self.config = Settings(_env_file=None, ENVIRONMENT="test", API_MAX_BODY_BYTES=1024)
        self.app.add_middleware(APISecurityMiddleware, settings=self.config, limiter=self.limiter)
        @self.app.post("/auth/login")
        @self.app.post("/auth/register")
        async def credentials(request: Request):
            await request.json()
            return {"ok": True}
        @self.app.post("/json")
        async def echo(request: Request):
            return await request.json()
        @self.app.get("/research")
        async def research():
            return {"ok": True}
        @self.app.get("/failure")
        async def failure():
            raise RuntimeError("credential-must-not-leak")
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_bounded_auth_client_and_account_attempts(self):
        # Account budget spans changing clients (neither existence nor password matters).
        for index in range(10):
            with TestClient(self.app, client=(f"198.51.100.{index}", 1000)) as client:
                self.assertEqual(client.post("/auth/login", json={"email": "same@example.com"}).status_code, 200)
        limited = self.client.post("/auth/login", json={"email": "SAME@example.com"})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["retry-after"], "900")
        self.clock[0] = 901
        self.assertEqual(self.client.post("/auth/login", json={"email": "same@example.com"}).status_code, 200)

    def test_client_budget_ignores_spoofed_forwarding_headers(self):
        for index in range(20):
            response = self.client.post("/auth/login", json={"email": f"user{index}@example.com"},
                headers={"X-Forwarded-For": f"192.0.2.{index}", "Forwarded": f"for=192.0.2.{index}"})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post("/auth/login", json={"email": "fresh@example.com"}).status_code, 429)

    def test_registration_and_public_research_limits(self):
        for index in range(5):
            self.assertEqual(self.client.post("/auth/register", json={"email": f"u{index}@example.com"}).status_code, 200)
        self.assertEqual(self.client.post("/auth/register", json={"email": "six@example.com"}).status_code, 429)
        for _ in range(120):
            self.assertEqual(self.client.get("/research").status_code, 200)
        self.assertEqual(self.client.get("/research").status_code, 429)

    def test_declared_and_streamed_body_limits_and_content_type(self):
        self.assertEqual(self.client.post("/json", content=b"x" * 1025).status_code, 413)
        self.assertEqual(self.client.post("/json", content=b"{}", headers={"Content-Type": "text/plain"}).status_code, 415)
        self.assertEqual(self.client.post("/json", json={"ok": True}).status_code, 200)
        self.assertEqual(self.client.post("/json", content="{}", headers={"Content-Length": "-1"}).status_code, 400)
        # Direct chunked ASGI request omits Content-Length, so the streaming
        # boundary rather than the declared-length shortcut must reject it.
        async def run():
            chunks = iter([{"type": "http.request", "body": b"a" * 700, "more_body": True},
                           {"type": "http.request", "body": b"b" * 700, "more_body": False}])
            output = []
            async def receive(): return next(chunks)
            async def send(message): output.append(message)
            await self.app({"type": "http", "method": "POST", "path": "/json", "raw_path": b"/json",
                "query_string": b"", "headers": [(b"content-type", b"application/json")],
                "client": ("chunked-test", 1), "scheme": "http", "server": ("testserver", 80)}, receive, send)
            self.assertEqual(output[0]["status"], 413)
        asyncio.run(run())

    def test_error_sanitization_query_bound_and_response_headers(self):
        response = self.client.get("/failure")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Internal server error"})
        self.assertNotIn("credential", response.text)
        self.assertEqual(self.client.get("/research?q=" + "x" * 4097).status_code, 414)
        response = self.client.get("/research")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_limiter_memory_is_bounded_without_eviction_bypass(self):
        limiter = WindowLimiter(clock=lambda: self.clock[0], max_keys=2)
        self.assertEqual(limiter.check([("a", 1, 60)]), 0)
        self.assertEqual(limiter.check([("b", 1, 60)]), 0)
        self.assertEqual(limiter.check([("c", 1, 60)]), 60)
        self.assertEqual(limiter.check([("a", 1, 60)]), 60)
        self.assertEqual(len(limiter.windows), 2)
        self.clock[0] = 61
        self.assertEqual(limiter.check([("c", 1, 60)]), 0)

    def test_secure_configuration_constraints(self):
        config = Settings(_env_file=None, ENVIRONMENT="test", AUTH_COOKIE_SAMESITE="none")
        self.assertIn("auth_cookie_samesite", config.configuration_errors())
        config.ENVIRONMENT = "production"
        config.JWT_EXPIRE_MINUTES = 10080
        self.assertIn("jwt_expiry", config.configuration_errors())
        self.assertIn("gateway_rate_limit", config.configuration_errors())
        self.assertTrue(config.cookie_secure)

    def test_research_query_bounds_before_database_work(self):
        from unittest.mock import Mock
        from app.database import get_db
        from app.routers import props, players
        app = FastAPI()
        app.include_router(props.router, prefix="/props")
        app.include_router(players.router, prefix="/players")
        db = Mock()
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            for path in ("/props/feed?limit=0", "/props/feed?offset=-1", "/props/games?limit=-1",
                         "/props/discover?offset=1000001", "/props/discover?search=" + "a" * 121,
                         "/players/search?q=" + "a" * 81,
                         "/players/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/research?line=nan",
                         "/players/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/research?offer_line=inf"):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 422)
        db.query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
