"""Configuration, auth and probe checks; never use the application database."""
import asyncio
import os
from datetime import datetime, timedelta
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
import jwt
from jwt import InvalidTokenError as JWTError
from app.config import Settings
from app.services.readiness_service import check_readiness
from app import auth
from app.main import app, lifespan
from app.database import get_db, Base


def production(**changes):
    return Settings(_env_file=None, **dict(ENVIRONMENT="production",
        JWT_SECRET="only-tests-8cR7eQ1wT4yU9iO2pA5sD6fG", DATABASE_URL="postgresql://fixture@127.0.0.1/proppulse_test_config",
        CORS_ORIGINS=["https://research.example.invalid"], GATEWAY_RATE_LIMIT_ENABLED=True, **changes))


class SecurityHardeningTests(unittest.TestCase):
    def test_shared_example_can_be_loaded_without_frontend_extra_error(self):
        from pathlib import Path
        example = Path(__file__).resolve().parents[2] / ".env.example"
        with patch.dict(os.environ, {}, clear=True):
            config = Settings(_env_file=example)
        self.assertEqual(config.configuration_errors(), [])
        self.assertFalse(config.LIVE_REFRESH_ENABLED)
        self.assertEqual(config.the_odds_api_key, "")

    def test_production_secrets_rejected(self):
        for value in ("", " ", "changeme", "replace-with-an-example-key", "a" * 64, "placeholder" * 8):
            config = production()
            config.JWT_SECRET = value
            self.assertIn("jwt_secret", config.configuration_errors())

    def test_missing_production_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings(_env_file=None, ENVIRONMENT="production").configuration_errors(),
                             ["cors_origins", "database_url", "gateway_rate_limit", "jwt_secret"])

    def test_explicit_test_configuration(self):
        self.assertEqual(Settings(_env_file=None, ENVIRONMENT="test").configuration_errors(), [])
        self.assertEqual(production().configuration_errors(), [])

    def test_invalid_origins(self):
        for value in ("*", "https://*.vercel.app", "null", "http://example.invalid", "https://host/path",
                      "https://user:password@host", "https://host?query", "https://host:bad"):
            config = production()
            config.CORS_ORIGINS = [value]
            self.assertIn("cors_origins", config.configuration_errors())

    def test_cors_actual_and_preflight(self):
        # The real app's default development origins; no lifespan/database opened.
        client = TestClient(app)
        for origin, allowed in (("http://localhost:3000", True), ("https://evil.invalid", False)):
            response = client.get("/health", headers={"Origin": origin})
            self.assertEqual(response.headers.get("access-control-allow-origin"), origin if allowed else None)
            response = client.options("/users/me", headers={"Origin": origin,
                "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
            self.assertEqual(response.status_code, 200 if allowed else 400)

    def test_exact_selection_patch_preflight(self):
        client = TestClient(app)
        for path in ("/users/me/saved/selections/fixture", "/users/me/slip/items/fixture"):
            headers = {"Origin": "http://localhost:3000",
                       "Access-Control-Request-Method": "PATCH",
                       "Access-Control-Request-Headers": "authorization,content-type"}
            response = client.options(path, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertIn("PATCH", response.headers["access-control-allow-methods"])
            self.assertEqual(client.patch(path, json={}).status_code, 401)
            headers["Origin"] = "https://untrusted.invalid"
            self.assertEqual(client.options(path, headers=headers).status_code, 400)

    def test_database_unavailable_sanitized_and_recovers(self):
        engine = Mock()
        engine.connect.side_effect = RuntimeError("credential-must-not-leak")
        self.assertEqual(check_readiness(engine, production()),
                         {"status": "not_ready", "reason": "database_unavailable"})
        connection = Mock()
        engine.connect.side_effect = None
        engine.connect.return_value.__enter__ = Mock(return_value=connection)
        engine.connect.return_value.__exit__ = Mock(return_value=False)
        with patch("app.services.readiness_service.validate_database"):
            self.assertEqual(check_readiness(engine, production()), {"status": "ready"})

    def test_configuration_failure_does_not_connect(self):
        engine = Mock()
        self.assertEqual(check_readiness(engine, Settings(_env_file=None, ENVIRONMENT="production"))["reason"], "configuration")
        engine.connect.assert_not_called()

    def test_startup_never_writes_schema_or_launches_disabled_refresh(self):
        async def run():
            async with lifespan(app):
                pass
        with patch("app.main.settings", Settings(_env_file=None, ENVIRONMENT="test")), \
             patch.object(Base.metadata, "create_all") as ddl, patch("app.main.LiveRefresh") as refresh:
            asyncio.run(run())
            ddl.assert_not_called()
            refresh.return_value.start.assert_not_called()

    def test_production_startup_requires_readiness(self):
        async def run():
            async with lifespan(app):
                pass
        with patch("app.main.settings", production()), \
             patch("app.main.check_readiness", return_value={"status": "not_ready", "reason": "schema_revision"}), \
             patch("app.main.LiveRefresh") as refresh:
            with self.assertRaisesRegex(RuntimeError, "schema_revision"):
                asyncio.run(run())
            refresh.assert_not_called()

    def test_invalid_configuration_startup_rejected(self):
        async def run():
            async with lifespan(app):
                pass
        with patch("app.main.settings", Settings(_env_file=None, ENVIRONMENT="production")):
            with self.assertRaisesRegex(RuntimeError, "Invalid application configuration"):
                asyncio.run(run())

    def test_jwt_requires_subject_expiry_and_valid_uuid(self):
        for payload in ({"sub": str(uuid4())}, {"exp": datetime.utcnow()+timedelta(minutes=1)},
                        {"sub": "bad", "exp": datetime.utcnow()+timedelta(minutes=1)},
                        {"sub": str(uuid4()), "exp": datetime.utcnow()-timedelta(minutes=1)}):
            token = jwt.encode(payload, auth.settings.JWT_SECRET, algorithm="HS256")
            with self.assertRaises(JWTError):
                auth.decode_subject(token)
        subject = str(uuid4())
        self.assertEqual(auth.decode_subject(auth.create_token(subject)), subject)

    def test_wrong_signature_and_algorithm(self):
        payload = {"sub": str(uuid4()), "exp": datetime.utcnow()+timedelta(minutes=1)}
        for secret, algorithm in (("wrong-secret", "HS256"), (auth.settings.JWT_SECRET, "HS384")):
            with self.assertRaises(JWTError):
                auth.decode_subject(jwt.encode(payload, secret, algorithm=algorithm))

    def test_unknown_user_token_is_generic_unauthorized(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None
        app.dependency_overrides[get_db] = lambda: db
        self.addCleanup(app.dependency_overrides.clear)
        response = TestClient(app).get("/users/me", headers={"Authorization": "Bearer " + auth.create_token(str(uuid4()))})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid token")

    def test_unknown_email_pays_password_verification_cost(self):
        from app.routers import users
        from app.schemas import UserLogin
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch.object(users, "verify_password", return_value=False) as verify:
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as raised:
                users.login(UserLogin(email="absent@example.com", password="fixture-password"), db)
            self.assertEqual(raised.exception.detail, "Invalid credentials")
            verify.assert_called_once_with("fixture-password", users._DUMMY_PASSWORD_HASH)

    def test_password_hashing_no_silent_truncation(self):
        hashed = auth.hash_password("fixture-password")
        self.assertNotEqual(hashed, "fixture-password")
        self.assertTrue(auth.verify_password("fixture-password", hashed))
        self.assertFalse(auth.verify_password("wrong", hashed))
        self.assertFalse(auth.verify_password("a"*73, hashed))
        self.assertFalse(auth.verify_password("fixture-password", "invalid-hash"))

    def test_private_endpoints_and_no_test_routes(self):
        db = Mock()
        app.dependency_overrides[get_db] = lambda: db
        self.addCleanup(app.dependency_overrides.clear)
        client = TestClient(app)
        for path in ("/users/me", "/users/me/saved", "/users/me/slip"):
            self.assertEqual(client.get(path).status_code, 401)
            self.assertEqual(client.get(path, headers={"Authorization": "Bearer bad"}).status_code, 401)
        db.query.assert_not_called()
        self.assertFalse(any(route.path.startswith("/__test__") for route in app.routes))

    def test_liveness_and_readiness_status(self):
        client = TestClient(app)
        self.assertEqual(client.get("/health").json(), {"status": "ok"})
        with patch("app.main.check_readiness", return_value={"status": "not_ready", "reason": "database_unavailable"}):
            response = client.get("/ready")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_password_validation_does_not_echo_input(self):
        client = TestClient(app)
        proof = client.get("/auth/csrf").json()["csrf_token"]
        response = client.post("/auth/register", json={"email": "fixture@example.com", "password": "short"},
            headers={"Origin": "http://localhost:3000", "X-CSRF-Token": proof})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('"input"', response.text)
