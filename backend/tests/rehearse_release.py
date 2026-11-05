r"""Operator-invoked local recovery rehearsal. Never uses configured development DB.

Run from backend: .\venv\Scripts\python.exe tests/rehearse_release.py [--browsers]
Creates/removes only its own random, labelled PostgreSQL 15 tmpfs container.
Evidence and custom-format backup remain in ignored data/odds_runs/m3h/.
"""
import argparse
import hashlib
import http.client
from http.cookies import SimpleCookie
import json
import os
import re
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler
from uuid import UUID, uuid4

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
EVIDENCE = BACKEND / "data" / "odds_runs" / "m3h"
sys.path.insert(0, str(BACKEND))


def clean_environment(source):
    # PGHOSTADDR/PGSERVICE can reroute libpq despite an explicit URL host.
    return {key: value for key, value in source.items()
            if not key.upper().startswith(("PG", "DOCKER_"))
            and key.upper() != "PROPPULSE_TEST_POSTGRES_URL"}


def docker_args(*args):
    endpoint = "npipe:////./pipe/docker_engine" if os.name == "nt" else "unix:///var/run/docker.sock"
    return ["docker", "--host", endpoint, *args]


def owned_container(state, identity, name, port):
    if (not re.fullmatch(r"[a-f0-9]{64}", identity)
            or not re.fullmatch(r"proppulse-test-m3h-[a-f0-9]{12}", name)
            or state.get("Id") != identity or state.get("Name") != "/" + name
            or state.get("Config", {}).get("Labels", {}).get("proppulse.rehearsal") != "m3h"
            or state.get("NetworkSettings", {}).get("Ports", {}).get("5432/tcp")
                != [{"HostIp": "127.0.0.1", "HostPort": str(port)}]
            or any(mount.get("Type") != "tmpfs" for mount in state.get("Mounts", []))
            or state.get("HostConfig", {}).get("Tmpfs", {}).get("/var/lib/postgresql/data")
                != "rw,noexec,nosuid,size=512m"):
        raise RuntimeError("Refusing unowned or non-disposable container")


def server_target(value, port):
    allowed = {f"postgresql://rehearsal_reader@127.0.0.1:{port}/proppulse_test_m3h_restore",
               "postgresql://rehearsal@127.0.0.1:1/proppulse_test_offline", "sqlite:///:memory:"}
    if value not in allowed:
        raise RuntimeError("Refusing non-rehearsal database target")


def stop_tree(proc):
    if proc.poll() is None:
        if os.name == "nt":
            # Only a PID created by this runner; never image-name/broad cleanup.
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


PROCESS_GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}


def child_server():
    """Actual app/lifespan; no dependency, route, refresh or readiness replacement."""
    cleaned = clean_environment(os.environ)
    os.environ.clear()
    os.environ.update(cleaned)
    identity, name, port = (os.environ[key] for key in
                           ("REHEARSAL_CONTAINER_ID", "REHEARSAL_CONTAINER_NAME", "REHEARSAL_DB_PORT"))
    state = json.loads(subprocess.check_output(docker_args("inspect", identity), timeout=15))[0]
    owned_container(state, identity, name, port)
    server_target(os.environ.get("DATABASE_URL"), port)
    if (os.environ.get("ENVIRONMENT") != "staging" or os.environ.get("LIVE_REFRESH_ENABLED") != "false"
            or os.environ.get("THE_ODDS_API_KEY") or os.environ.get("BALLDONTLIE_API_KEY")):
        raise RuntimeError("Refusing unsafe rehearsal environment")
    import httpx
    from unittest.mock import patch
    from sqlalchemy import event
    import app.config
    # Deliberately ignore all env files; retain staging validation, including HTTPS.
    app.config.settings = app.config.Settings(_env_file=None)
    effective_settings = app.config.settings
    from app.database import engine
    from app.main import app
    import uvicorn
    stats = {"external_http_attempts": 0, "external_socket_attempts": 0,
             "subprocess_attempts": 0, "sql_writes": []}
    def save_stats():
        import threading
        stats["refresh_enabled"] = effective_settings.LIVE_REFRESH_ENABLED
        stats["refresh_threads"] = sum(t.name == "live-provider-refresh" for t in threading.enumerate())
        Path(os.environ["REHEARSAL_STATS"]).write_text(json.dumps(stats), encoding="utf-8")

    @app.middleware("http")
    async def record_stats(request, call_next):
        try:
            return await call_next(request)
        finally:
            save_stats()
    original_connect = socket.socket.connect

    def connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            stats["external_socket_attempts"] += 1
            raise AssertionError("Non-loopback egress blocked")
        return original_connect(sock, address)

    def forbidden(*args, **kwargs):
        stats["external_http_attempts"] += 1
        save_stats()
        raise AssertionError("Outbound HTTP blocked")

    async def forbidden_async(*args, **kwargs):
        return forbidden()

    def no_process(*args, **kwargs):
        stats["subprocess_attempts"] += 1
        save_stats()
        raise AssertionError("Subprocess blocked")

    @event.listens_for(engine, "before_cursor_execute")
    def observe(conn, cursor, statement, *args):
        verb = statement.strip().split()[0].upper()
        if verb in {"CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE", "TRUNCATE"}:
            stats["sql_writes"].append(verb)
        save_stats()

    try:
        with patch.object(socket.socket, "connect", connect), \
                patch.object(httpx.HTTPTransport, "handle_request", forbidden), \
                patch.object(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_async), \
                patch.object(http.client.HTTPConnection, "connect", forbidden), \
                patch.object(subprocess, "Popen", no_process):
            uvicorn.run(app, host="127.0.0.1", port=int(os.environ["REHEARSAL_PORT"]),
                        lifespan="on", log_level="warning", access_log=False)
    finally:
        Path(os.environ["REHEARSAL_STATS"]).write_text(json.dumps(stats), encoding="utf-8")


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browsers", action="store_true", help="Requires previously built frontend")
    options = parser.parse_args()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    name = "proppulse-test-m3h-" + uuid4().hex[:12]
    report = {"container": name, "checks": {}, "completed": False}
    container_id = None
    processes = []
    cleaned = clean_environment(os.environ)
    os.environ.clear()
    os.environ.update(cleaned)

    def command(args, *, cwd=BACKEND, env=None, log=None, timeout=240):
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **PROCESS_GROUP)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_tree(proc)
            stdout, stderr = proc.communicate(timeout=10)
            if log:
                (EVIDENCE / log).write_bytes(stdout + stderr)
            raise RuntimeError("Rehearsal command timed out") from None
        if log:
            (EVIDENCE / log).write_bytes(stdout + stderr)
        if proc.returncode:
            raise RuntimeError("Command failed: " + str(args[0]) + "; inspect " + str(log or "captured output"))
        return stdout.decode().strip()

    def docker(*args):
        return command(docker_args(*args))

    def sql(database, statement):
        return docker("exec", name, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "rehearsal",
                      "-d", database, "-Atc", statement)

    auth_cookies = {}

    def request(port, path, body=None, token=None, csrf=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        elif auth_cookies:
            # This operator-only loopback HTTP rehearsal explicitly transports
            # production Secure cookies; browser Secure delivery requires HTTPS.
            headers["Cookie"] = "; ".join(key + "=" + value for key, value in auth_cookies.items())
        if csrf:
            headers.update({"Origin": "https://rehearsal.invalid", "X-CSRF-Token": csrf})
        req = Request(f"http://127.0.0.1:{port}" + path,
                      data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            response = build_opener(ProxyHandler({})).open(req, timeout=15)
        except HTTPError as exc:
            response = exc
        with response:
            for value in response.headers.get_all("Set-Cookie", []):
                parsed = SimpleCookie()
                parsed.load(value)
                for key, cookie in parsed.items():
                    auth_cookies[key] = cookie.value
            return response.status, json.loads(response.read())

    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    try:
        if options.browsers:
            for browser_port in (8000, 3199):
                with socket.socket() as guard:
                    guard.bind(("127.0.0.1", browser_port))
        # Cached image only: no implicit pull, Compose, bind mount or named volume.
        container_id = docker("run", "--pull=never", "--detach", "--name", name,
            "--label", "proppulse.rehearsal=m3h", "--memory=512m", "--cpus=1", "--pids-limit=128",
            "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=512m",
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_USER=rehearsal",
            "-e", "POSTGRES_DB=proppulse_test_m3h_source", "-p", "127.0.0.1::5432", "postgres:15-alpine")
        report["container_id"] = container_id
        report["image"] = json.loads(docker("inspect", container_id))[0]["Image"]
        port = int(docker("port", name, "5432/tcp").split(":")[-1])
        container_state = json.loads(docker("inspect", container_id))[0]
        report["storage"] = {"mounts": container_state.get("Mounts"),
                             "tmpfs": container_state.get("HostConfig", {}).get("Tmpfs"),
                             "ports": container_state.get("NetworkSettings", {}).get("Ports")}
        owned_container(container_state, container_id, name, port)
        for _ in range(60):
            ready = subprocess.run(docker_args("exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "rehearsal"), capture_output=True, timeout=10)
            if ready.returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError("Disposable PostgreSQL not ready")
        report["postgres"] = sql("proppulse_test_m3h_source", "SHOW server_version")
        assert report["postgres"].startswith("15.")
        for database in ("proppulse_test_m3h_restore", "proppulse_test_m3h_suite", "proppulse_test_m3h_browser"):
            docker("exec", name, "createdb", "-U", "rehearsal", database)
        source_url = f"postgresql://rehearsal@127.0.0.1:{port}/proppulse_test_m3h_source"
        restored_url = source_url.replace("_source", "_restore")
        env = dict(os.environ, DATABASE_URL=source_url, ENVIRONMENT="test", LIVE_REFRESH_ENABLED="false",
                   JWT_SECRET=secrets.token_urlsafe(48), THE_ODDS_API_KEY="", BALLDONTLIE_API_KEY="")
        # Before any app/database import: every effective target is this container.
        os.environ.update({key: env[key] for key in ("DATABASE_URL", "ENVIRONMENT", "LIVE_REFRESH_ENABLED",
                                                   "JWT_SECRET", "THE_ODDS_API_KEY", "BALLDONTLIE_API_KEY")})
        import app.config
        app.config.settings = app.config.Settings(_env_file=None)
        from alembic import command as alembic
        from alembic.config import Config
        from sqlalchemy import create_engine, inspect, text
        from sqlalchemy.orm import Session
        from app import models as m
        from app.auth import hash_password, create_token
        from app.services.readiness_service import check_readiness
        engine = create_engine(source_url)
        restored = create_engine(restored_url)
        assert not inspect(engine).get_table_names()
        config = Config(str(BACKEND / "alembic.ini"))
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            alembic.upgrade(config, "20261014_01")
        assert sql("proppulse_test_m3h_source", "SELECT version_num FROM alembic_version") == "20261014_01"
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            alembic.upgrade(config, "20261014_02")
        assert check_readiness(engine, app.config.settings) == {"status": "ready"}
        report["checks"]["empty_migration_01_then_02"] = "passed"
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        uid = lambda n: str(UUID(int=n))
        with Session(engine) as db, db.begin():
            db.add(m.Event(id=uid(100), provider="the_odds_api", provider_event_id="synthetic-recovery-event",
                sport_key="basketball_nba", home_team="Rehearsal Home", away_team="Rehearsal Away",
                scheduled_start_at=now + timedelta(days=2)))
            db.add(m.Player(id=uid(200), name="Synthetic Recovery Player", team="Rehearsal Away", team_abbr="RHR", sport="NBA"))
            db.add(m.User(id=uid(400), email="recovery@example.com", hashed_password=hash_password("Recovery-test-42!"),
                fav_sports=["NBA"], fav_players=[uid(200)], fav_prop_types=["points"]))
            db.flush()
            for n in (300, 301):
                db.add(m.Prop(id=uid(n), player_id=uid(200), event_id=uid(100) if n == 300 else None,
                    prop_type="points", line=20.5, sportsbook="FanDuel", odds_sport_key="basketball_nba",
                    odds_event_id="synthetic-recovery-event" if n == 300 else "synthetic-legacy",
                    game_time=now + timedelta(days=2), opponent="Rehearsal Home"))
            db.add(m.Slip(id=uid(401), user_id=uid(400)))
            db.flush()
            db.add_all([m.PropBook(prop_id=uid(300), sportsbook="FanDuel", line=20.5, over_odds=-110, under_odds=None,
                            provider_observed_at=now, ingested_at=now),
                        m.PropBookSnapshot(prop_id=uid(300), sportsbook="FanDuel", line=19.5, over_odds=-105, under_odds=-115),
                        m.SavedProp(user_id=uid(400), prop_id=uid(300)),
                        m.SlipItem(slip_id=uid(401), prop_id=uid(300), side="under", sportsbook="FanDuel", line=19.5),
                        m.Interaction(user_id=uid(400), prop_id=uid(300), action="save"),
                        m.FatigueScore(player_id=uid(200), fatigue_score=.2),
                        m.Ranking(prop_id=uid(300), user_id=uid(400), final_score=.5)])
            for n in range(12):
                db.add(m.PlayerGameLog(player_id=uid(200), sport="NBA", external_game_id=f"synthetic-{n}",
                    game_date=now-timedelta(days=n+1), stats={"points": 25, "minutes": 30}, source="espn_nba"))

        def fingerprint(target):
            result = {}
            with target.connect() as conn:
                for table in sorted(inspect(target).get_table_names()):
                    order = "version_num" if table == "alembic_version" else "id"
                    rows = conn.execute(text(f'SELECT row_to_json(t)::text FROM "{table}" t ORDER BY "{order}"')).scalars().all()
                    result[table] = {"count": len(rows), "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest()}
            return result

        baseline = fingerprint(engine)
        backup_start = time.perf_counter()
        docker("exec", name, "pg_dump", "-U", "rehearsal", "-Fc", "--no-owner", "--no-acl",
               "-f", "/tmp/m3h.dump", "proppulse_test_m3h_source")
        backup = EVIDENCE / "recovery-fixture.dump"
        docker("cp", name + ":/tmp/m3h.dump", str(backup))
        report["backup_seconds"] = round(time.perf_counter()-backup_start, 3)
        report["backup_bytes"] = backup.stat().st_size
        report["backup_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
        start = time.perf_counter()
        docker("exec", name, "pg_restore", "-U", "rehearsal", "--exit-on-error", "--single-transaction",
               "--no-owner", "--no-acl", "-d", "proppulse_test_m3h_restore", "/tmp/m3h.dump")
        report["restore_seconds"] = round(time.perf_counter()-start, 3)
        assert baseline == fingerprint(restored)
        report["tables"] = baseline
        report["checks"]["full_row_restore_preservation"] = "passed"
        assert check_readiness(restored, app.config.settings) == {"status": "ready"}
        # Every FK is validated after pg_restore; restoring constraints checks all rows.
        assert sql("proppulse_test_m3h_restore", "SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND contype IN ('f','c') AND NOT convalidated") == "0"
        with restored.connect() as conn:
            try:
                conn.execute(text("UPDATE props SET event_id=NULL WHERE id=:id"), {"id": uid(300)})
            except Exception as exc:
                assert getattr(exc.orig, "pgcode", None) == "23514"
            else:
                raise AssertionError("Immutable link guard did not fire")
        report["checks"]["restored_fk_constraints_trigger_revision"] = "passed"
        sql("proppulse_test_m3h_restore", "REVOKE CREATE ON SCHEMA public FROM PUBLIC; CREATE ROLE rehearsal_reader LOGIN; GRANT CONNECT ON DATABASE proppulse_test_m3h_restore TO rehearsal_reader; GRANT USAGE ON SCHEMA public TO rehearsal_reader; GRANT SELECT ON ALL TABLES IN SCHEMA public TO rehearsal_reader; ALTER ROLE rehearsal_reader SET default_transaction_read_only=on")
        # Isolated fixture acknowledgement only; no live gateway is certified.
        api_env = dict(env, ENVIRONMENT="staging", GATEWAY_RATE_LIMIT_ENABLED="true",
                       DATABASE_URL=restored_url.replace("rehearsal@", "rehearsal_reader@"),
                       CORS_ORIGINS='["https://rehearsal.invalid"]', REHEARSAL_PORT=str(free_port()),
                       REHEARSAL_CONTAINER_ID=container_id, REHEARSAL_CONTAINER_NAME=name, REHEARSAL_DB_PORT=str(port))

        def start_server(label, changes=None, success=True):
            child_env = dict(api_env, **(changes or {}), REHEARSAL_STATS=str(EVIDENCE / (label + "-stats.json")))
            child_env = {key: value for key, value in child_env.items() if value is not None}
            log = open(EVIDENCE / (label + ".log"), "wb")
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"], cwd=BACKEND,
                                    env=child_env, stdout=log, stderr=log, **PROCESS_GROUP)
            processes.append((proc, log))
            for _ in range(80):
                if proc.poll() is not None:
                    break
                try:
                    if request(int(child_env["REHEARSAL_PORT"]), "/health")[0] == 200:
                        assert success, label + " unexpectedly started"
                        return proc, child_env
                except (URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(.1)
            assert not success and proc.poll() is not None, label + " unexpected startup state"
            log.flush()
            assert "Application startup failed" in (EVIDENCE / (label + ".log")).read_text()
            return proc, child_env

        for label, changes in (("default-secret", {"JWT_SECRET": "changeme"}), ("missing-secret", {"JWT_SECRET": None}),
                               ("non-postgres", {"DATABASE_URL": "sqlite:///:memory:"}),
                               ("wrong-database", {"DATABASE_URL": "postgresql://rehearsal@127.0.0.1:1/proppulse_test_offline"})):
            start_server(label, changes, success=False)
            report["checks"][label] = "startup refused"
        sql("proppulse_test_m3h_restore", "UPDATE alembic_version SET version_num='incompatible'")
        start_server("wrong-revision", success=False)
        sql("proppulse_test_m3h_restore", "UPDATE alembic_version SET version_num='20261014_02'")
        proc, child_env = start_server("restored-api")
        api_port = int(child_env["REHEARSAL_PORT"])
        assert request(api_port, "/ready") == (200, {"status": "ready"})
        assert request(api_port, "/__test__/manifest")[0] == 404
        # Current production process must observe schema deterioration and recovery.
        sql("proppulse_test_m3h_restore", "ALTER TABLE events DROP CONSTRAINT ck_events_distinct_teams; ALTER TABLE events ADD CONSTRAINT ck_events_distinct_teams CHECK (lower(trim(home_team)) != lower(trim(away_team))) NOT VALID")
        assert request(api_port, "/ready") == (503, {"status": "not_ready", "reason": "schema_prerequisites"})
        start_server("unvalidated-constraint", {"REHEARSAL_PORT": str(free_port())}, success=False)
        sql("proppulse_test_m3h_restore", "ALTER TABLE events VALIDATE CONSTRAINT ck_events_distinct_teams")
        sql("proppulse_test_m3h_restore", "DROP INDEX ix_props_event_id")
        assert request(api_port, "/ready")[0] == 503
        sql("proppulse_test_m3h_restore", "CREATE INDEX ix_props_event_id ON props(event_id)")
        sql("proppulse_test_m3h_restore", "DROP INDEX ix_users_email; INSERT INTO users (id,email,hashed_password) SELECT '00000000-0000-0000-0000-000000000999',email,hashed_password FROM users LIMIT 1")
        with restored.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            try:
                conn.execute(text("CREATE UNIQUE INDEX CONCURRENTLY ix_users_email ON users(email)"))
            except Exception as exc:
                assert getattr(exc.orig, "pgcode", None) == "23505"
            else:
                raise AssertionError("Invalid index challenge unexpectedly succeeded")
        assert request(api_port, "/ready") == (503, {"status": "not_ready", "reason": "schema_prerequisites"})
        sql("proppulse_test_m3h_restore", "DROP INDEX ix_users_email; DELETE FROM users WHERE id='00000000-0000-0000-0000-000000000999'; CREATE UNIQUE INDEX ix_users_email ON users(email)")
        assert request(api_port, "/ready") == (200, {"status": "ready"})
        proof = request(api_port, "/auth/csrf")[1]["csrf_token"]
        status, login = request(api_port, "/auth/login", {"email": "recovery@example.com", "password": "Recovery-test-42!"}, csrf=proof)
        assert status == 200
        assert login == {"ok": True}
        paths = ["/users/me", "/users/me/saved", "/users/me/slip", "/props/feed", "/props/discover",
                 "/props/games", "/props/game?event_id="+uid(100), "/players/"+uid(200)+"/research?prop_id="+uid(300)]
        report["api_statuses"] = {}
        for path in paths:
            status, body = request(api_port, path)
            assert status == 200, (path, status)
            report["api_statuses"][path] = status
        choice = request(api_port, "/users/me/slip")[1]["slip"]["items"][0]
        assert choice["side"] == "under" and choice["selection"]["sportsbook"] == "FanDuel" and choice["selection"]["line"] == 19.5
        # Existing tokens and bcrypt hashes survive restore when signing secret is retained.
        assert request(api_port, "/users/me", token=create_token(uid(400)))[0] == 200
        assert fingerprint(restored) == baseline
        stats = json.loads(Path(child_env["REHEARSAL_STATS"]).read_text())
        assert stats == {"external_http_attempts": 0, "external_socket_attempts": 0,
                         "subprocess_attempts": 0, "sql_writes": [], "refresh_enabled": False, "refresh_threads": 0}
        report["production_process_stats"] = stats
        proc.terminate()
        proc.wait(timeout=10)
        report["checks"]["real_staging_lifespan_auth_research_readonly_preservation"] = "passed"
        suite_env = dict(env, PROPPULSE_TEST_POSTGRES_URL=source_url.replace("_source", "_suite"))
        start = time.perf_counter()
        command([sys.executable, "tests/run_no_provider_http.py"], env=suite_env, log="backend-suite.log", timeout=300)
        report["backend_suite_seconds"] = round(time.perf_counter()-start, 3)
        report["checks"]["backend_suite"] = "passed"
        if options.browsers:
            command(["node", "node_modules/@playwright/test/cli.js", "test", "--config", "playwright.config.cjs"], cwd=ROOT/"frontend", env=env, log="browser-mocked-desktop.log")
            command(["node", "node_modules/@playwright/test/cli.js", "test", "--config", "playwright.mobile.config.cjs"], cwd=ROOT/"frontend", env=env, log="browser-mocked-mobile.log")
            browser_env = dict(env, PROPPULSE_TEST_POSTGRES_URL=source_url.replace("_source", "_browser"))
            log = open(EVIDENCE/"browser-api.log", "wb")
            browser = subprocess.Popen([sys.executable, "tests/integration_server.py"], cwd=BACKEND, env=browser_env, stdout=log, stderr=log, **PROCESS_GROUP)
            processes.append((browser, log))
            for _ in range(100):
                assert browser.poll() is None, "Browser API exited"
                try:
                    status, manifest = request(8000, "/__test__/manifest")
                    if status == 200:
                        assert manifest["event_id"] == uid(100) and manifest["prop_id"] == uid(300)
                        break
                except (URLError, ConnectionError):
                    pass
                assert browser.poll() is None, "Browser API exited"
                time.sleep(.1)
            else:
                raise RuntimeError("Owned browser fixture failed readiness")
            for channel in ("chrome", "msedge"):
                command(["node", "node_modules/@playwright/test/cli.js", "test", "--config", "playwright.integration.config.cjs"],
                        cwd=ROOT/"frontend", env=dict(env, PLAYWRIGHT_CHANNEL=channel), log="browser-real-"+channel+".log")
            preservation = request(8000, "/__test__/preservation")[1]
            assert preservation["unchanged"] and preservation["provider_http_attempts"] == 0
            (EVIDENCE/"browser-preservation.json").write_text(json.dumps(preservation, indent=2))
            report["checks"]["browser_matrix"] = "passed"
        engine.dispose()
        restored.dispose()
        report["completed"] = True
    finally:
        try:
            for proc, log in processes:
                try:
                    stop_tree(proc)
                finally:
                    log.close()
        finally:
            try:
                if container_id:
                    # Exact ID + random name + label must match before removal.
                    state = json.loads(docker("inspect", container_id))[0]
                    assert state["Name"] == "/" + name and state["Config"]["Labels"]["proppulse.rehearsal"] == "m3h"
                    docker("rm", "--force", container_id)
                    report["container_removed"] = True
            finally:
                (EVIDENCE/"recovery-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        child_server()
    else:
        run()
