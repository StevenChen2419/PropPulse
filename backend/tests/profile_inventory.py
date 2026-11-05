"""Manual, synthetic PostgreSQL profile; requires guarded disposable test URL.

Run from backend: python tests/profile_inventory.py <ignored-output.json>
Creates/removes a random test schema only. No provider/network or app lifespan.
"""
import http.client
import json
import os
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration_server import integration_target


def main():
    target = integration_target(os.environ.get("PROPPULSE_TEST_POSTGRES_URL", ""))
    os.environ.update(DATABASE_URL=target.render_as_string(hide_password=False), ENVIRONMENT="test",
                      LIVE_REFRESH_ENABLED="false", JWT_SECRET="isolated-profile-only", THE_ODDS_API_KEY="",
                      BALLDONTLIE_API_KEY="")
    import app.config
    app.config.settings = app.config.Settings(_env_file=None)
    import test_event_migration_postgres as fixtures
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.orm import sessionmaker
    from fastapi.testclient import TestClient
    import httpx
    from app.database import get_db
    from app.models import Event, Player, Prop, PropBook, PropBookSnapshot, PlayerGameLog, User, SavedProp, Slip, SlipItem
    from app.auth import create_token
    from app.services.game_log_fields import provider_season
    from app.services.game_identity_service import event_context
    from app.main import app
    import app.routers.props as props_router

    fixtures.EventMigrationPostgresTests.setUpClass()
    fixture = fixtures.EventMigrationPostgresTests("test_fresh_bootstrap_is_complete_and_repeated_head_has_no_metadata_diffs")
    fixture.setUp()
    reader = None
    attempts = []
    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("External HTTP forbidden in inventory profile")
    async def forbidden_async(*args, **kwargs):
        forbidden()
    try:
        fixture.upgrade()
        admin = fixture.engine
        Session = sessionmaker(bind=admin)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session.begin() as db:
            events = [Event(id=str(uuid4()), provider="the_odds_api", sport_key="basketball_nba",
                provider_event_id=f"profile-{n}", home_team=f"Fixture Home {n}", away_team=f"Fixture Away {n}",
                scheduled_start_at=now+timedelta(days=2, minutes=n)) for n in range(120)]
            players = [Player(id=str(uuid4()), name=f"Synthetic Player {n}", sport="NBA", team=f"Fixture Away {n//2}",
                              team_abbr="FIX") for n in range(240)]
            db.add_all(events + players)
            db.flush()
            props = []
            for n in range(6000):
                ev = events[n % 120]
                props.append(Prop(id=str(uuid4()), player_id=players[n % 240].id,
                    event_id=ev.id if n < 5900 else None, odds_event_id=ev.provider_event_id if n < 5900 else f"conflict-{n}",
                    odds_sport_key=ev.sport_key, prop_type=("points", "assists", "rebounds", "threes", "blocks")[n//240 % 5],
                    line=20.5, line_24h_ago=19.5, sportsbook="FanDuel", game_time=ev.scheduled_start_at,
                    opponent=ev.home_team, is_home=False, popularity_count=n % 30))
            # Conflicting unlinked namespaces sharing the exact old key.
            props[-1].player_id = props[-2].player_id
            props[-1].game_time = props[-2].game_time
            props[-1].opponent = props[-2].opponent
            db.add_all(props)
            db.flush()
            for n, prop in enumerate(props):
                observed = now-timedelta(hours=7) if n % 20 == 19 else now
                for book, line in (("FanDuel", 20.5), ("DraftKings", 21.5 if n % 3 == 0 else 20.5)):
                    db.add(PropBook(prop_id=prop.id, sportsbook=book, line=line, over_odds=-110, under_odds=-115,
                                   provider_observed_at=observed, ingested_at=now, updated_at=now))
                    db.add(PropBookSnapshot(prop_id=prop.id, sportsbook=book, line=19.5, over_odds=-105,
                                           under_odds=-120, captured_at=now-timedelta(hours=2)))
            season = provider_season("NBA", events[0].scheduled_start_at)
            for player in players:
                for n in range(20):
                    db.add(PlayerGameLog(player_id=player.id, sport="NBA", source="espn_nba",
                        external_game_id=f"synthetic-{n}", game_date=now-timedelta(days=n+1), is_home=n%2 == 0,
                        opponent="Fixture Opponent", stats={"points": 25+n%4, "assists": 24, "rebounds": 26,
                        "threes": 23, "blocks": 22, "minutes": 32, "season": season}))
            user = User(id=str(uuid4()), email="profile@example.invalid", hashed_password="unused")
            slip = Slip(id=str(uuid4()), user_id=user.id)
            db.add(user)
            db.flush()
            db.add(slip)
            db.flush()
            db.add_all([SavedProp(user_id=user.id, prop_id=prop.id) for prop in props[:20]])
            db.add_all([SlipItem(slip_id=slip.id, prop_id=prop.id, side="under", sportsbook="FanDuel", line=19.5)
                        for prop in props[:10]])
            ids = {"event": events[0].id, "player": players[0].id, "prop": props[0].id,
                   "token": create_token(user.id)}
            ambiguous = props_router.prop_context(props[-2])["game_key"]
        with admin.begin() as conn:
            conn.execute(text("ANALYZE"))
        reader = create_engine(target, execution_options={"postgresql_readonly": True})
        @event.listens_for(reader, "connect")
        def search_path(connection, record):
            with connection.cursor() as cursor:
                cursor.execute('SET search_path TO "' + fixture.schema + '"')
            connection.commit()
        ReadSession = sessionmaker(bind=reader)
        def db_dependency():
            with ReadSession() as db:
                yield db
        app.dependency_overrides[get_db] = db_dependency
        queries = []
        @event.listens_for(reader, "after_cursor_execute")
        def observe(conn, cursor, statement, params, context, executemany):
            queries.append((statement, params, max(cursor.rowcount, 0)))
        result = {"inventory": {"events":120, "players":240, "props":6000, "offers":12000,
            "snapshots":12000, "game_logs":4800, "saved":20, "slip_items":10}, "measurements": {}}
        paths = {"upcoming": "/props/todays-games?limit=20", "event": f"/props/game?event_id={ids['event']}",
            "feed": "/props/feed?limit=20", "feed_page2": "/props/feed?limit=20&offset=20",
            "discover": "/props/discover?limit=20", "discover_page2": "/props/discover?limit=20&offset=20",
            "research": f"/players/{ids['player']}/research?prop_id={ids['prop']}",
            "status": "/props/ingestion-status", "saved": "/users/me/saved", "slip": "/users/me/slip"}
        client = TestClient(app)
        headers = {"Authorization": "Bearer " + ids["token"]}
        with patch.object(props_router, "read_ingestion_status", return_value={"source":"synthetic_profile", "sports":{}}), \
             patch.object(httpx.HTTPTransport, "handle_request", forbidden), \
             patch.object(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_async), \
             patch.object(http.client.HTTPConnection, "connect", forbidden):
            for name, path in paths.items():
                times = []
                for _ in range(3):
                    queries.clear()
                    start = time.perf_counter()
                    response = client.get(path, headers=headers)
                    times.append(round((time.perf_counter()-start)*1000, 2))
                    assert response.status_code == 200, (name, response.status_code)
                captured = list(queries)
                data = response.json()
                record = {"ms":times, "median_ms":statistics.median(times), "queries":len(captured),
                          "sql_rows_returned":sum(row[2] for row in captured),
                          "total":data.get("total") if isinstance(data, dict) else len(data),
                          "returned":len(data.get("props", data.get("saved", []))) if isinstance(data, dict) else len(data)}
                plans = {}
                for sql, params, _ in captured:
                    if sql not in plans and sql.lstrip().upper().startswith("SELECT"):
                        with reader.connect() as conn:
                            plan = conn.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params).scalar()
                        plans[sql] = plan
                def scanned(node):
                    value = ((node.get("Actual Rows",0)+node.get("Rows Removed by Filter",0)) * node.get("Actual Loops",1)
                             if node.get("Node Type", "").endswith("Scan") else 0)
                    return value+sum(scanned(child) for child in node.get("Plans", []))
                record["plan_scan_row_visits"] = sum(scanned(plans[sql][0]["Plan"]) for sql, _, _ in captured if sql in plans)
                record["plans"] = plans
                tracemalloc.start()
                client.get(path, headers=headers)
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                record["python_peak_mib"] = round(peak/1024**2, 2)
                result["measurements"][name] = record
                print(name, {key: val for key,val in record.items() if key != "plans"}, flush=True)
            assert client.get("/props/game", params={"game_key":ambiguous}).status_code == 409
        result["external_http_attempts"] = len(attempts)
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    finally:
        app.dependency_overrides.clear()
        if reader:
            reader.dispose()
        fixture.doCleanups()


if __name__ == "__main__":
    main()
