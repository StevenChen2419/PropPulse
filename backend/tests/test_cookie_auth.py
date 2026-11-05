"""Actual authentication routes with isolated sessions; no DB/lifespan/network."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from app import auth
from app.config import Settings
from app.database import get_db
from app.routers import users
from app.services import session_security as security


class CookieAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = auth.hash_password("fixture-password")

    def setUp(self):
        self.config = Settings(_env_file=None, ENVIRONMENT="test",
            JWT_SECRET="test-only-Cookie-proof-7493-L0ng-secret",
            CORS_ORIGINS=["http://localhost:3000"], JWT_EXPIRE_MINUTES=120)
        for target in (auth, security):
            patcher = patch.object(target, "settings", self.config)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.user = SimpleNamespace(id=str(uuid4()), email="fixture@example.com",
            hashed_password=self.password_hash)
        self.db = Mock()
        self.db.query.return_value.filter.return_value.first.return_value = self.user
        app = FastAPI()
        app.include_router(users.router, prefix="/auth")
        app.dependency_overrides[get_db] = lambda: self.db

        @app.api_route("/private", methods=["GET", "POST", "PATCH", "DELETE"])
        def private(user=Depends(auth.get_current_user)):
            return {"id": user.id}

        @app.post("/optional")
        def optional(user=Depends(auth.get_optional_user)):
            return {"id": user.id if user else None}

        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.body = {"email": self.user.email, "password": "fixture-password"}

    def proof(self):
        response = self.client.get("/auth/csrf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return {"Origin": "http://localhost:3000", "X-CSRF-Token": response.json()["csrf_token"]}

    def login(self):
        response = self.client.post("/auth/login", json=self.body, headers=self.proof())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        return response

    def test_login_cookie_attributes_no_token_json_and_identity(self):
        response = self.login()
        cookie = response.headers["set-cookie"]
        for marker in ("proppulse_session=", "HttpOnly", "Path=/", "SameSite=lax", "Max-Age=7200"):
            self.assertIn(marker, cookie)
        self.assertNotIn("Domain=", cookie)
        self.assertNotIn("Secure", cookie)
        self.assertEqual(self.client.get("/private").json(), {"id": self.user.id})

    def test_production_host_only_secure_cookie_names(self):
        self.config.ENVIRONMENT = "production"
        response = self.client.get("/auth/csrf")
        cookie = response.headers["set-cookie"]
        for marker in ("__Host-proppulse_csrf=", "HttpOnly", "Path=/", "Secure", "SameSite=lax"):
            self.assertIn(marker, cookie)
        self.assertNotIn("Domain=", cookie)
        from starlette.responses import Response
        session = Response()
        security.set_session(session, "fixture")
        self.assertIn("__Host-proppulse_session=", session.headers["set-cookie"])
        self.assertIn("Secure", session.headers["set-cookie"])

    def test_login_register_logout_require_csrf_and_trusted_origin(self):
        for path in ("/auth/login", "/auth/register", "/auth/logout"):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json=self.body).status_code, 403)
                headers = self.proof()
                headers["Origin"] = "https://evil.invalid"
                self.assertEqual(self.client.post(path, json=self.body, headers=headers).status_code, 403)
        self.db.query.assert_not_called()

    def test_csrf_referer_fallback_null_origin_and_tampering(self):
        headers = self.proof()
        headers.pop("Origin")
        headers["Referer"] = "http://localhost:3000/login"
        self.assertEqual(self.client.post("/auth/login", json=self.body, headers=headers).status_code, 200)
        for changes in ({"Origin": "null"}, {"Origin": "http://localhost:3000.evil.invalid"},
                        {"X-CSRF-Token": "0" * 64}, {"Referer": "http://user@localhost:3000/login"}):
            headers = self.proof()
            if "Referer" in changes:
                headers.pop("Origin")
            headers.update(changes)
            self.assertEqual(self.client.post("/auth/logout", headers=headers).status_code, 403)

    def test_cookie_mutations_require_session_bound_proof_and_logout_clears(self):
        old = self.proof()
        self.login()
        self.assertEqual(self.client.post("/private", headers=old).status_code, 403)
        for method in (self.client.post, self.client.patch, self.client.delete):
            self.assertEqual(method("/private").status_code, 403)
            self.assertEqual(method("/private", headers=self.proof()).status_code, 200)
        self.assertEqual(self.client.post("/optional").status_code, 403)
        self.assertEqual(self.client.post("/optional", headers=self.proof()).status_code, 200)
        proof = self.proof()
        response = self.client.post("/auth/logout", headers=proof)
        self.assertEqual(response.json(), {"ok": True})
        self.assertNotIn("proppulse_session", self.client.cookies)
        self.assertNotIn("proppulse_csrf", self.client.cookies)
        self.assertEqual(self.client.get("/private").status_code, 401)
        self.assertEqual(self.client.post("/auth/logout", headers=proof).status_code, 403)

    def test_cookie_precedence_and_bearer_only_tooling(self):
        bearer = {"Authorization": "Bearer " + auth.create_token(self.user.id)}
        self.assertEqual(self.client.post("/private", headers=bearer).status_code, 200)
        self.client.cookies.set("proppulse_session", "invalid")
        self.assertEqual(self.client.get("/private", headers=bearer).status_code, 401)
        self.assertEqual(self.client.post("/private", headers=bearer).status_code, 403)

    def test_registration_success_cookie_and_duplicate_race_generic_errors(self):
        self.db.query.return_value.filter.return_value.first.return_value = None
        self.db.refresh.side_effect = lambda user: setattr(user, "id", str(uuid4()))
        response = self.client.post("/auth/register", json=self.body, headers=self.proof())
        self.assertEqual(response.json(), {"ok": True})
        self.assertIn("proppulse_session", self.client.cookies)
        self.db.query.return_value.filter.return_value.first.return_value = self.user
        duplicate = self.client.post("/auth/register", json=self.body, headers=self.proof())
        self.db.query.return_value.filter.return_value.first.return_value = None
        self.db.commit.side_effect = IntegrityError("private email", {}, Exception("database secret"))
        race = self.client.post("/auth/register", json=self.body, headers=self.proof())
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(race.status_code, 400)
        self.assertEqual(duplicate.json(), race.json())
        self.assertEqual(race.json(), {"detail": "Unable to register account"})
        self.db.rollback.assert_called_once()

    def test_csrf_proof_not_reusable_across_nonce_or_session(self):
        first = self.proof()
        self.client.cookies.clear()
        self.proof()
        self.assertEqual(self.client.post("/auth/logout", headers=first).status_code, 403)

    def test_auth_input_bounds_before_password_hash_or_database_work(self):
        for changes in ({"username": "x" * 101}, {"password": "x" * 73},
                        {"password": "é" * 37}):
            body = dict(self.body, **changes)
            response = self.client.post("/auth/register", json=body, headers=self.proof())
            self.assertEqual(response.status_code, 422)
        self.db.query.assert_not_called()
        from pydantic import ValidationError
        from app.schemas import UserPreferences
        self.assertEqual(UserPreferences(fav_players=[self.user.id]).fav_players, [self.user.id])
        for values in (["player"] * 101, ["x" * 81]):
            with self.assertRaises(ValidationError):
                UserPreferences(fav_players=values)


if __name__ == "__main__":
    unittest.main()
