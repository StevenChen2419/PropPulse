"""Actual application for security browser checks in an EMPTY disposable DB.

Requires an explicit loopback proppulse_test_* URL on a non-development port.
No production lifespan, env-file settings, provider HTTP, or real sports data.
Run from backend; the browser suite uses port 8199 and frontend port 3199.
"""
import http.client
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def disposable_target(value):
    from sqlalchemy.engine import make_url
    if any(key.upper().startswith("PG") for key in os.environ):
        raise RuntimeError("Ambient PostgreSQL connection settings forbidden")
    try:
        target = make_url(value)
        valid = (target.get_backend_name() == "postgresql" and target.host == "127.0.0.1"
                 and target.port not in (None, 5432) and not target.query
                 and re.fullmatch(r"proppulse_test_[a-z0-9_]+", target.database or ""))
    except Exception:
        valid = False
    if not valid:
        raise RuntimeError("Explicit loopback disposable test database on a non-5432 port required")
    return target


def main():
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import sessionmaker
    target = disposable_target(os.environ.get("PROPPULSE_TEST_POSTGRES_URL", ""))
    os.environ.update(DATABASE_URL=target.render_as_string(hide_password=False),
                      ENVIRONMENT="test", LIVE_REFRESH_ENABLED="false",
                      JWT_SECRET="security-browser-fixture-only-4f837ae1dc0926b5",
                      CORS_ORIGINS='["http://127.0.0.1:3199"]',
                      THE_ODDS_API_KEY="", BALLDONTLIE_API_KEY="")
    import app.config
    app.config.settings = app.config.Settings(_env_file=None)
    from app.database import get_db
    from app.models import Event, Player, Prop, PropBook
    engine = create_engine(target)
    # Verify effective libpq connection routing before schema changes.
    with engine.connect() as connection:
        parameters = connection.connection.driver_connection.get_dsn_parameters()
        if (parameters.get("host") != "127.0.0.1"
                or int(parameters.get("port", 5432)) != target.port
                or connection.execute(text("SELECT current_database()")).scalar() != target.database):
            raise RuntimeError("Disposable PostgreSQL routing verification failed")
        if inspect(connection).get_table_names():
            raise RuntimeError("Security browser runner requires an empty disposable database")
    from alembic import command
    from alembic.config import Config
    migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.upgrade(migration, "head")
    Session = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    prop_id = str(UUID(int=9300))
    with Session.begin() as db:
        event = Event(id=str(UUID(int=9100)), provider="the_odds_api",
                      sport_key="basketball_nba", provider_event_id="fixture-security-browser",
                      home_team="Security Fixture Home", away_team="Security Fixture Away",
                      scheduled_start_at=now + timedelta(days=2))
        player = Player(id=str(UUID(int=9200)), name="Security Fixture Player",
                        team="Security Fixture Away", team_abbr="FIX", sport="NBA")
        db.add_all([event, player])
        db.flush()
        prop = Prop(id=prop_id, player_id=player.id, event_id=event.id, prop_type="points",
                    line=20.5, sportsbook="FanDuel", game_time=event.scheduled_start_at,
                    odds_sport_key=event.sport_key, odds_event_id=event.provider_event_id,
                    opponent=event.home_team, is_home=False)
        db.add(prop)
        db.flush()
        db.add(PropBook(prop_id=prop.id, sportsbook="FanDuel", line=20.5,
                        over_odds=-110, under_odds=-115, provider_observed_at=now,
                        ingested_at=now, updated_at=now))
    from app.main import app
    def db_dependency():
        with Session() as db:
            yield db
    app.dependency_overrides[get_db] = db_dependency
    # Never display retained real-provider status alongside synthetic fixtures.
    import app.routers.props as props_router
    props_router.read_ingestion_status = lambda: {"source": "synthetic_security_test", "sports": {}}
    attempts = []
    @app.get("/__test__/security-guard")
    def security_guard():
        return {"provider_http_attempts": len(attempts)}

    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("External/provider HTTP forbidden in security browser runner")
    async def forbidden_async(*args, **kwargs):
        return forbidden()
    import httpx
    import requests
    import uvicorn
    print("Security browser fixture ready: disposable PostgreSQL; synthetic data; HTTP blocked", flush=True)
    try:
        with patch.object(httpx.HTTPTransport, "handle_request", forbidden), \
             patch.object(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_async), \
             patch.object(requests.sessions.Session, "request", forbidden), \
             patch.object(http.client.HTTPConnection, "connect", forbidden):
            uvicorn.run(app, host="127.0.0.1", port=8199, lifespan="off", log_level="warning",
                        proxy_headers=False, access_log=False)
    finally:
        print(f"Provider/external HTTP attempts: {len(attempts)}", flush=True)
        engine.dispose()


if __name__ == "__main__":
    main()
