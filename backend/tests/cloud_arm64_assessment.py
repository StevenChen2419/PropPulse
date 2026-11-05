"""ARM64 assessment: disposable empty schema/auth only; never provider data."""
import json
import os
import platform
import resource
from unittest.mock import patch

if not __debug__:
    raise RuntimeError("Assessment requires enabled safety assertions")

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"])
if (url.get_backend_name() != "postgresql" or url.host != "pp-assess-pg"
        or url.port != 5432 or url.database != "assessment"
        or url.username != "assessment" or url.query):
    raise RuntimeError("Only the explicit disposable assessment database is allowed")
assert platform.machine() == "aarch64"
assert os.getuid() == 10001
from app.config import settings
assert settings.production and not settings.LIVE_REFRESH_ENABLED and not settings.configuration_errors()
if settings.DATABASE_URL != os.environ["DATABASE_URL"]:
    raise RuntimeError("Effective database configuration differs from the assessment target")

def forbidden(*args, **kwargs):
    raise AssertionError("External HTTP forbidden in assessment")

import httpx
import requests
from alembic.config import Config
from alembic import command
with patch.object(requests.sessions.Session, "request", forbidden), patch.object(httpx.HTTPTransport, "handle_request", forbidden):
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("select current_database(), current_user")).one() == ("assessment", "assessment")
        assert connection.execute(text("select version()")).scalar().find("aarch64") >= 0
    command.upgrade(Config("/app/alembic.ini"), "20261022_05")
    with engine.connect() as connection:
        assert connection.execute(text("select version_num from alembic_version")).scalar() == "20261022_05"
    from app.main import app
    from fastapi.testclient import TestClient
    with TestClient(app, base_url="https://api.example.com") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json() == {"status": "ready"}
        assert client.get("/players/search").status_code == 200
        assert client.get("/props/discover").status_code == 200
        origin = {"Origin": "https://app.example.com"}
        proof = client.get("/auth/csrf").json()["csrf_token"]
        response = client.post("/auth/register", headers={**origin, "X-CSRF-Token": proof}, json={"email": "assessment@example.com", "password": "DisposableAssessment!472"})
        assert response.status_code == 200, response.status_code
        cookie = response.headers["set-cookie"]
        assert "__Host-proppulse_session=" in cookie and "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie and "Domain=" not in cookie
        assert client.get("/users/me").status_code == 200
        assert client.get("/users/me/saved").status_code == 200
        assert client.get("/users/me/slip").status_code == 200
        assert client.post("/auth/logout", headers=origin).status_code == 403
        proof = client.get("/auth/csrf").json()["csrf_token"]
        assert client.post("/auth/logout", headers={**origin, "X-CSRF-Token": proof}).status_code == 200
    engine.dispose()
print(json.dumps({"architecture": platform.machine(), "revision": "20261022_05", "health_ready_empty_research_auth_csrf": True, "max_rss_kib_emulated": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
