"""Explicitly invoked disposable PostgreSQL 15 inventory benchmark and JSON oracle.

Never loads the application lifespan or a configured development database. Run from
backend with PROPPULSE_TEST_POSTGRES_URL targeting a loopback proppulse_test_ DB:
  venv/Scripts/python.exe tests/benchmark_inventory.py --label baseline --size 6000
  venv/Scripts/python.exe tests/benchmark_inventory.py --label optimized --size 6000 --compare baseline
Evidence is ignored under data/odds_runs/m3i. Each run owns and removes one schema.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid4, uuid5

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
SPORTS = {"NBA": "basketball_nba", "NFL": "americanfootball_nfl", "NHL": "icehockey_nhl",
          "MLB": "baseball_mlb", "WNBA": "basketball_wnba"}
MARKETS = {"NBA": ("points", "assists"), "WNBA": ("points", "assists"),
           "NFL": ("pass_yds", "rush_yds"), "MLB": ("hits", "total_bases"),
           "NHL": ("shots_on_goal", "points")}


class ClockMeta(type):
    def __instancecheck__(cls, value):
        return isinstance(value, datetime)


class FrozenClock(datetime, metaclass=ClockMeta):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return NOW.replace(tzinfo=None)


def uid(value):
    return str(uuid5(NAMESPACE_URL, "proppulse-m3i/" + str(value)))


def seed(session, size):
    from app.models import Event, Player, Prop, PropBook, PropBookSnapshot, PlayerGameLog, FatigueScore, User, SavedProp, Slip, SlipItem
    user = User(id=uid("user"), email="inventory@example.invalid", hashed_password="unused",
                fav_sports=["NBA"], fav_players=[], fav_prop_types=[])
    session.add(user)
    rows = []
    players = []
    props = []
    for i in range(math.ceil(size / 10)):
        sport = list(SPORTS)[i % 5]
        player = Player(id=uid(f"player/{i}"), name=f"Fixture Player {i:05}", sport=sport,
                        team=f"Home {i % 20}", team_abbr=f"H{i % 20}", position="G")
        players.append(player)
        rows.append(player)
        if i % 7:
            rows.append(FatigueScore(id=uid(f"fatigue/{i}"), player_id=player.id,
                fatigue_score=(i % 5) / 10, workload_score=(i % 5) / 10,
                games_in_7d=3, rolling_minutes_7d=90, scored_at=NOW.replace(tzinfo=None),
                risk_flags=[], shap_reasons=[]))
        if i % 13:
            for j in range(24):
                # Current and prior seasons; holes are intentional.
                date = NOW - timedelta(days=(j + 1 if j < 12 else 365 + j))
                stats = {market: float(10 + (j % 7)) for market in MARKETS[sport]}
                if j == 4:
                    stats = {}
                if j == 5:
                    stats["completed"] = False
                rows.append(PlayerGameLog(id=uid(f"log/{i}/{j}"), player_id=player.id,
                    sport=sport, external_game_id=f"history-{i}-{j}", game_date=date.replace(tzinfo=None),
                    opponent="Visitor", is_home=True, stats=stats,
                    source="mlb_stats_api" if sport == "MLB" else f"espn_{sport.lower()}"))
    session.add_all(rows)
    session.flush()
    rows = []
    for i in range(size):
        player = players[i // 10]
        sport = player.sport
        # Ten candidate markets/player; authoritative games hold only ten props.
        start = (NOW + timedelta(hours=4, days=(i // 10) % 3)).replace(tzinfo=None)
        if i % 101 == 0:
            start = NOW.replace(tzinfo=None)  # start equality must be unavailable
        event = None
        if i % 4 != 0:
            key = f"event/{i // 10}/{start.isoformat()}"
            event = session.info.setdefault("events", {}).get(key)
            if event is None:
                event = Event(id=uid(key), provider="the_odds_api", provider_event_id=f"fixture-{i // 10}-{start.isoformat()}",
                    sport_key=SPORTS[sport], home_team=player.team, away_team="Visitor", scheduled_start_at=start,
                    updated_at=NOW.replace(tzinfo=None))
                session.info["events"][key] = event
                rows.append(event)
        market = MARKETS[sport][i % 2]
        line = 9.5 + (i % 3)
        prop = Prop(id=uid(f"prop/{i}"), player_id=player.id, event_id=event.id if event else None,
            prop_type=market, line=line, line_24h_ago=line + (0.5 if i % 2 else 0),
            sportsbook="FanDuel", odds_event_id=(f"legacy-{i // 10}" if event is None else event.provider_event_id),
            odds_sport_key=SPORTS[sport], odds_last_seen_at=NOW.replace(tzinfo=None),
            game_time=start - timedelta(days=1) if event and i % 83 == 0 else start,
            opponent="Visitor", is_home=True, is_active=i % 97 != 0,
            popularity_count=i % 9, created_at=NOW.replace(tzinfo=None))
        props.append(prop)
        rows.append(prop)
        state = i % 19
        observed = (NOW - timedelta(minutes=10 if state < 15 else 90 if state == 15 else 361)).replace(tzinfo=None)
        if state != 18:
            for b, book in enumerate(("FanDuel", "DraftKings", "BetMGM")):
                rows.append(PropBook(id=uid(f"offer/{i}/{b}"), prop_id=prop.id, sportsbook=book,
                    line=line + (1 if b == 2 else 0), over_odds=-110 + b * 5,
                    under_odds=-115 if state != 17 else None,
                    provider_observed_at=observed, ingested_at=observed, updated_at=observed))
        if i % 10 == 0:
            for age in (24, 12):
                rows.append(PropBookSnapshot(id=uid(f"snapshot/{i}/{age}"), prop_id=prop.id,
                    sportsbook="FanDuel", line=line + (0.5 if age == 24 else 0),
                    over_odds=-115, under_odds=-105,
                    captured_at=(NOW - timedelta(hours=age)).replace(tzinfo=None)))
    session.add_all(rows)
    session.flush()
    slip = Slip(id=uid("slip"), user_id=user.id, status="open", created_at=NOW.replace(tzinfo=None))
    session.add(slip)
    session.flush()
    for i, prop in enumerate(props[::10][:20]):
        session.add(SavedProp(id=uid(f"saved/{i}"), user_id=user.id, prop_id=prop.id, saved_at=NOW.replace(tzinfo=None)))
        if i < 10:
            session.add(SlipItem(id=uid(f"item/{i}"), slip_id=slip.id, prop_id=prop.id,
                side="under" if i % 2 else "over", sportsbook="BetMGM", line=prop.line + (1 if i % 2 else 2)))
    other = User(id=uid("other-user"), email="other-inventory@example.invalid", hashed_password="unused",
                 fav_sports=[], fav_players=[], fav_prop_types=[])
    session.add(other)
    session.flush()
    other_slip = Slip(id=uid("other-slip"), user_id=other.id, status="open", created_at=NOW.replace(tzinfo=None))
    session.add(other_slip)
    session.flush()
    session.add(SavedProp(id=uid("other-saved"), user_id=other.id, prop_id=props[-1].id, saved_at=NOW.replace(tzinfo=None)))
    session.add(SlipItem(id=uid("other-item"), slip_id=other_slip.id, prop_id=props[-1].id,
                         side="over", sportsbook="DraftKings", line=props[-1].line))
    session.commit()
    return next(p.event_id for p in props if p.event_id), players[1].id


def fingerprint(engine):
    from sqlalchemy import text
    from app.database import Base
    with engine.connect() as conn:
        return {name: conn.execute(text(f'SELECT count(*), md5(coalesce(string_agg(row_to_json(t)::text, \'\' ORDER BY id), \'\')) FROM "{name}" t')).one()._asdict()
                for name in sorted(Base.metadata.tables)}


def rss_mib():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 2**20
    except ImportError:
        if os.name != "nt":
            return None
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (field, ctypes.c_size_t) for field in ("PeakWorkingSetSize", "WorkingSetSize",
                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        function = ctypes.windll.psapi.GetProcessMemoryInfo
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        function.restype = wintypes.BOOL
        if function(wintypes.HANDLE(-1), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize / 2**20
        return None


def source_hashes(app_root):
    """Git blob hashes normalize CRLF exactly as the repository text files do."""
    result = {}
    for path in sorted(app_root.rglob("*.py")):
        content = path.read_bytes().replace(b"\r\n", b"\n")
        result[str(path.relative_to(app_root)).replace("\\", "/")] = hashlib.sha1(
            b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    return result


def exact_json_equal(left, right):
    """Object-key ordering is immaterial; JSON scalar types and array order are exact."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(exact_json_equal(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(exact_json_equal(a, b) for a, b in zip(left, right))
    return left == right


def discover_stage_diagnostics(module, Session):
    """Separate instrumented request; never mix these timings with latency targets.

    Net deltas describe bytes retained across each call, not total allocations.
    Nested trend/serialization stages overlap. Global peak observations are high
    watermarks since trace start, never independent/additive per-stage peaks.
    """
    stages = {}
    names = ("read_prop_inventory", "load_game_logs", "eligible_offers", "build_exact_line_trends",
             "discovery_history_summary", "discovery_history_windows",
             "score_discovery_prop", "serialize_prop", "latest_refresh")
    def wrapped(name, original):
        def measure(*args, **kwargs):
            before, _ = tracemalloc.get_traced_memory()
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                after, peak = tracemalloc.get_traced_memory()
                record = stages.setdefault(name, {"calls": 0, "elapsed_ms": 0, "net_retained_bytes": 0,
                                                   "observed_global_peak_bytes": 0})
                record["calls"] += 1
                record["elapsed_ms"] += elapsed * 1000
                record["net_retained_bytes"] += after - before
                record["observed_global_peak_bytes"] = max(record["observed_global_peak_bytes"], peak)
        return measure
    with ExitStack() as stack, Session() as session:
        from sqlalchemy import text
        session.execute(text("SET TRANSACTION READ ONLY"))
        for name in names:
            if hasattr(module, name):
                stack.enter_context(patch.object(module, name, wrapped(name, getattr(module, name))))
        tracemalloc.start()
        started = time.perf_counter()
        try:
            result = module.get_discover(limit=20, offset=0, sport=None, prop_type=None,
                                         game_key=None, event_id=None, db=session)
            current, peak = tracemalloc.get_traced_memory()
            elapsed = time.perf_counter() - started
        finally:
            tracemalloc.stop()
    return {"stages": stages, "request_elapsed_ms": elapsed * 1000,
            "request_retained_bytes": current, "request_peak_bytes": peak,
            "returned": len(result["props"]), "total": result["total"],
            "note": "Separate diagnostics with instrumentation overhead; nested stages overlap. Net retained bytes are not allocation totals; global peaks are not additive."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, choices=[6000, 12000], required=True)
    parser.add_argument("--label", choices=["baseline", "optimized", "smoke"], required=True)
    parser.add_argument("--compare", choices=["baseline"])
    parser.add_argument("--baseline-source", action="store_true", help="Import preserved pre-optimization app snapshot")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--no-trace", action="store_true", help="Smoke checks only; no peak-memory measurements")
    parser.add_argument("--oracle-pages", action="store_true", help="Capture all feed/discover pages (slow baseline)")
    parser.add_argument("--concurrency-seconds", type=int, default=0)
    parser.add_argument("--stage-diagnostics", action="store_true", help="Separate instrumented Discover stage allocation request")
    parser.add_argument("--concurrent-oracle-once", action="store_true", help="Five clients compare all nine HTTP surfaces exactly against baseline once")
    args = parser.parse_args()
    if args.baseline_source:
        source = BACKEND / "data" / "odds_runs" / "m3i" / "baseline_source"
        if not (source / "app" / "routers" / "props.py").is_file():
            raise RuntimeError("Preserved baseline source is unavailable")
        sys.path.insert(0, str(source))
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.engine import make_url
    raw = os.environ.get("PROPPULSE_TEST_POSTGRES_URL", "")
    url = make_url(raw)
    if (url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or not (url.database or "").startswith("proppulse_test_") or url.query
            or any(key.upper().startswith("PG") for key in os.environ)):
        raise RuntimeError("Explicit loopback disposable proppulse_test_ target without PG overrides required")
    os.environ.update(DATABASE_URL=raw, LIVE_REFRESH_ENABLED="false", ENVIRONMENT="test",
                      THE_ODDS_API_KEY="", BALLDONTLIE_API_KEY="")
    import app.config
    app.config.settings = app.config.Settings(_env_file=None)
    from app.database import Base
    from app.routers import props, players, users
    from app.auth import get_current_user, get_optional_user
    from app.database import get_db
    from app.models import User
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    import httpx
    engine = create_engine(raw, pool_size=5, max_overflow=0, pool_timeout=30)
    schema = "m3i_" + uuid4().hex
    with engine.begin() as conn:
        if conn.execute(text("SHOW server_version_num")).scalar()[:2] != "15":
            raise RuntimeError("PostgreSQL 15 required")
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine.dispose()
    @event.listens_for(engine, "connect")
    def search_path(dbapi, record):
        with dbapi.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
        dbapi.commit()
    evidence = BACKEND / "data" / "odds_runs" / "m3i"
    evidence.mkdir(parents=True, exist_ok=True)
    target = evidence / f"{args.label}-{args.size}.json"
    Session = sessionmaker(bind=engine)
    try:
        Base.metadata.create_all(engine)
        with Session() as session:
            event_id, player_id = seed(session, args.size)
        with engine.begin() as conn:
            conn.execute(text("ANALYZE"))
        before = fingerprint(engine)
        app = FastAPI()
        app.include_router(props.router, prefix="/props")
        app.include_router(players.router, prefix="/players")
        app.include_router(users.user_router, prefix="/users")
        def database():
            with Session() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                yield session
        def user(db=__import__("fastapi").Depends(get_db)):
            return db.get(User, uid("user"))
        app.dependency_overrides.update({get_db: database, get_current_user: user, get_optional_user: user})
        endpoints = {"feed": "/props/feed?limit=20", "feed_deep": "/props/feed?limit=20&offset=2000",
            "discover": "/props/discover?limit=20", "discover_deep": "/props/discover?limit=20&offset=2000",
            "games": "/props/games?limit=20", "game": f"/props/game?event_id={event_id}",
            "research": f"/players/{player_id}/research", "saved": "/users/me/saved", "slip": "/users/me/slip"}
        sql = []
        captured = {}
        @event.listens_for(engine, "after_cursor_execute")
        def observe(conn, cursor, statement, parameters, context, many):
            sql.append({"sql": statement, "parameters": parameters, "rows": cursor.rowcount})
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE")):
                raise AssertionError("Benchmark attempted a write")
        report = {"size": args.size, "requests": args.requests, "clock": NOW.isoformat(),
                  "exclusions": [], "metrics": {}, "oracle": {}, "plans": {},
                  "method": "in-process TestClient, real PostgreSQL, isolated schema, read-only request transactions",
                  "schema": schema, "source_git_blob_hashes": source_hashes(Path(props.__file__).resolve().parents[1]),
                  "fixture_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "fixture_seed_sha256": hashlib.sha256(inspect.getsource(seed).replace("\r\n", "\n").encode()).hexdigest(),
                  "fixture_table_counts": {table: values["count"] for table, values in before.items()}}
        provider_http_attempts = {"count": 0}
        def blocked(*a, **kw):
            provider_http_attempts["count"] += 1
            raise AssertionError("Provider HTTP is forbidden")
        with ExitStack() as stack:
            # Freeze every loaded app module importing datetime. Instance checks still accept DB datetimes.
            for module in list(sys.modules.values()):
                if getattr(module, "__name__", "").startswith("app.") and getattr(module, "datetime", None) is datetime:
                    stack.enter_context(patch.object(module, "datetime", FrozenClock))
            stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", blocked))
            stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", blocked))
            import http.client
            stack.enter_context(patch.object(http.client.HTTPConnection, "connect", blocked))
            client = TestClient(app)
            for name, path in endpoints.items():
                client.get(path)  # warm-up
                timings = []
                counts = []
                rows = []
                for _ in range(args.requests):
                    sql.clear()
                    started = time.perf_counter()
                    response = client.get(path)
                    timings.append(1000 * (time.perf_counter() - started))
                    counts.append(len(sql))
                    rows.append(sum(max(0, q["rows"]) for q in sql))
                report["oracle"][name] = {"status": response.status_code, "body": response.json()}
                captured[name] = list(sql)
                peak = None
                if not args.no_trace:
                    tracemalloc.start()
                    client.get(path)
                    _, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                rss = rss_mib()
                body = response.json()
                report["metrics"][name] = {"median_ms": statistics.median(timings),
                    "p95_ms": sorted(timings)[math.ceil(.95 * len(timings))-1], "sql_count": counts,
                    "rows_returned_by_sql": rows, "traced_peak_mib": peak / 2**20 if peak is not None else None, "rss_mib": rss,
                    "returned": len(body.get("props", body.get("games", body.get("saved", (body.get("slip") or {}).get("items", []))))),
                    "total": body.get("total"), "status": response.status_code}
                print(name, json.dumps(report["metrics"][name]), flush=True)
                target.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            import cProfile
            import io
            import pstats
            profiler = cProfile.Profile()
            with Session() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                profiler.enable()
                props.get_discover(limit=20, offset=0, sport=None, prop_type=None,
                                   game_key=None, event_id=None, db=session)
                profiler.disable()
            profile_output = io.StringIO()
            pstats.Stats(profiler, stream=profile_output).sort_stats("cumulative").print_stats(45)
            report["discover_cprofile"] = profile_output.getvalue()
            if args.stage_diagnostics:
                report["discover_stage_diagnostics"] = discover_stage_diagnostics(props, Session)
            if args.concurrent_oracle_once:
                from concurrent.futures import ThreadPoolExecutor
                import gc
                baseline_report = json.loads((evidence / f"baseline-{args.size}.json").read_text(encoding="utf-8"))
                expected = {name: baseline_report["oracle"][name] for name in endpoints}
                del baseline_report
                gc.collect()
                def oracle_worker(index):
                    comparisons = {}
                    for name, path in endpoints.items():
                        try:
                            response = client.get(path)
                            actual = {"status": response.status_code, "body": response.json()}
                            match = exact_json_equal(expected[name], actual)
                            comparisons[name] = {"status": response.status_code, "equivalent": match}
                            if not match:
                                comparisons[name]["actual"] = actual
                        except Exception as exc:
                            comparisons[name] = {"equivalent": False, "error": type(exc).__name__}
                    return {"client": index, "surfaces": comparisons,
                            "equivalent": all(item["equivalent"] for item in comparisons.values())}
                with ThreadPoolExecutor(max_workers=5) as pool:
                    report["concurrent_oracle"] = list(pool.map(oracle_worker, range(5)))
                report["concurrent_oracle_equivalent"] = all(worker["equivalent"] for worker in report["concurrent_oracle"])
                report["concurrent_oracle_note"] = "Five concurrent clients each traverse all nine HTTP surfaces once; strict JSON scalar types, values, all keys and array order; fixed clock; zero exclusions."
            if args.oracle_pages:
                from fastapi.encoders import jsonable_encoder
                with Session() as session:
                    session.execute(text("SET TRANSACTION READ ONLY"))
                    report["oracle"]["games_all"] = jsonable_encoder(
                        props.get_games(limit=args.size, sport=None, db=session))
                for surface in ("feed", "discover"):
                    # Invoke the identical route implementation with an unbounded
                    # output limit, only for oracle capture (not an API contract or
                    # benchmark). This avoids O(pages * inventory) baseline work.
                    from fastapi.encoders import jsonable_encoder
                    with Session() as session:
                        session.execute(text("SET TRANSACTION READ ONLY"))
                        kwargs = dict(limit=args.size, offset=0, sport=None, prop_type=None,
                                      game_key=None, event_id=None, db=session)
                        if surface == "feed":
                            kwargs["user"] = session.get(User, uid("user"))
                        result = getattr(props, "get_" + surface)(**kwargs)
                        report["oracle"][surface + "_all"] = jsonable_encoder(result)
                # Additional complete responses verify filters, exact historical
                # selection and API failures without conflating them with timings.
                extra = {f"{surface}_{sport}": f"/props/{surface}?sport={sport}"
                         for surface in ("feed", "discover", "games") for sport in SPORTS}
                extra.update({
                    "bad_game_key": "/props/game?game_key=invalid",
                    "unknown_event": f"/props/game?event_id={uid('unknown-event')}",
                    "legacy_collision": "/props/game?game_key=NBA|2026-10-16T12:00:00|Visitor|Home%200",
                    "research_exact_prop": f"/players/{uid('player/1')}/research?prop_id={uid('prop/10')}",
                    "research_wrong_player": f"/players/{uid('player/1')}/research?prop_id={uid('prop/20')}",
                    "event_feed": f"/props/feed?event_id={event_id}",
                    "event_discover": f"/props/discover?event_id={event_id}",
                    "empty_offset": f"/props/feed?offset={args.size + 1}",
                    "empty_discover_offset": f"/props/discover?offset={args.size + 1}",
                    "todays_compatibility": "/props/todays-games",
                })
                for name, path in extra.items():
                    response = client.get(path)
                    report["oracle"][name] = {"status": response.status_code, "body": response.json()}
            if args.concurrency_seconds:
                from concurrent.futures import ThreadPoolExecutor
                import threading
                # Read-only transactions enforce write protection throughout;
                # drop verbose SQL capture to avoid attributing harness growth to
                # application RSS drift during the sustained concurrency test.
                event.remove(engine, "after_cursor_execute", observe)
                sql.clear()
                report["concurrency_rss_start_mib"] = rss_mib()
                report["concurrency_rss_series"] = []
                pool_acquisition_ms = []
                pool_usage = {"active": 0, "peak": 0}
                usage_lock = threading.Lock()
                original_do_get = engine.pool._do_get
                def timed_do_get():
                    started = time.perf_counter()
                    try:
                        return original_do_get()
                    finally:
                        pool_acquisition_ms.append((time.perf_counter() - started) * 1000)
                # Measurement of QueuePool acquisition includes queue wait and
                # connection creation; never present it as pure server wait.
                engine.pool._do_get = timed_do_get
                def checkout(*unused):
                    with usage_lock:
                        pool_usage["active"] += 1
                        pool_usage["peak"] = max(pool_usage["peak"], pool_usage["active"])
                def checkin(*unused):
                    with usage_lock:
                        pool_usage["active"] -= 1
                event.listen(engine, "checkout", checkout)
                event.listen(engine, "checkin", checkin)
                stop_monitor = threading.Event()
                concurrency_start = time.monotonic()
                def monitor():
                    while not stop_monitor.wait(5):
                        report["concurrency_rss_series"].append({
                            "elapsed_seconds": time.monotonic() - concurrency_start, "rss_mib": rss_mib()})
                monitor_thread = threading.Thread(target=monitor, daemon=True)
                monitor_thread.start()
                deadline = time.monotonic() + args.concurrency_seconds
                print("concurrency_started", json.dumps({"clients": 5, "seconds": args.concurrency_seconds,
                                                         "size": args.size}), flush=True)
                def worker(index):
                    result = {"requests": 0, "failures": [], "latencies_ms": [], "rss_samples_mib": [],
                              "latency_by_endpoint_ms": {name: [] for name in endpoints}}
                    while time.monotonic() < deadline:
                        name, path = list(endpoints.items())[result["requests"] % len(endpoints)]
                        start = time.perf_counter()
                        try:
                            response = client.get(path)
                            if response.status_code != 200:
                                result["failures"].append(response.status_code)
                        except Exception as exc:
                            result["failures"].append(type(exc).__name__)
                        latency = (time.perf_counter() - start) * 1000
                        result["latencies_ms"].append(latency)
                        result["latency_by_endpoint_ms"][name].append(latency)
                        result["requests"] += 1
                        if result["requests"] % 10 == 0:
                            result["rss_samples_mib"].append(rss_mib())
                    return result
                try:
                    with ThreadPoolExecutor(max_workers=5) as pool:
                        report["concurrency"] = list(pool.map(worker, range(5)))
                finally:
                    stop_monitor.set()
                    monitor_thread.join(timeout=10)
                    engine.pool._do_get = original_do_get
                    event.remove(engine, "checkout", checkout)
                    event.remove(engine, "checkin", checkin)
                report["concurrency_rss_end_mib"] = rss_mib()
                report["concurrency_target_seconds"] = args.concurrency_seconds
                report["concurrency_elapsed_seconds"] = time.monotonic() - concurrency_start
                report["concurrency_pool"] = {**pool_usage, "pool_size": 5, "max_overflow": 0,
                    "acquisition_ms": pool_acquisition_ms,
                    "note": "QueuePool._do_get elapsed time includes queue wait and any connection creation; not pure wait."}
                series = report["concurrency_rss_series"]
                valid_rss = [item["rss_mib"] for item in series if item["rss_mib"] is not None]
                warm_rss = [item["rss_mib"] for item in series if 30 <= item["elapsed_seconds"] <= 60 and item["rss_mib"] is not None]
                late_rss = [item["rss_mib"] for item in series
                            if args.concurrency_seconds - 30 <= item["elapsed_seconds"] <= args.concurrency_seconds and item["rss_mib"] is not None]
                report["concurrency_rss_summary"] = {
                    "minimum_mib": min(valid_rss, default=None), "maximum_mib": max(valid_rss, default=None),
                    "warm_30_60_seconds_median_mib": statistics.median(warm_rss) if warm_rss else None,
                    "final_30_seconds_median_mib": statistics.median(late_rss) if late_rss else None,
                    "late_minus_warm_mib": statistics.median(late_rss) - statistics.median(warm_rss) if warm_rss and late_rss else None}
                report["concurrency_by_endpoint"] = {}
                for name in endpoints:
                    latencies = [value for worker_result in report["concurrency"]
                                 for value in worker_result["latency_by_endpoint_ms"][name]]
                    report["concurrency_by_endpoint"][name] = {"requests": len(latencies),
                        "median_ms": statistics.median(latencies) if latencies else None,
                        "p95_ms": sorted(latencies)[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
                        "maximum_ms": max(latencies, default=None)}
                event.listen(engine, "after_cursor_execute", observe)
        event.remove(engine, "after_cursor_execute", observe)
        # Explain the actual bound SQL, never interpolate parameters.
        with engine.connect() as conn:
            for name, statements in captured.items():
                report["plans"][name] = []
                seen = set()
                for item in statements:
                    statement = item["sql"]
                    if not statement.lstrip().upper().startswith("SELECT") or statement in seen:
                        continue
                    seen.add(statement)
                    plan = conn.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, item["parameters"]).scalar()
                    report["plans"][name].append({"sql": statement, "plan": plan})
        after = fingerprint(engine)
        report["fingerprint_before"] = before
        report["fingerprint_after"] = after
        report["data_unchanged"] = before == after
        report["provider_http_attempts"] = provider_http_attempts["count"]
        if args.compare:
            baseline = json.loads((evidence / f"{args.compare}-{args.size}.json").read_text(encoding="utf-8"))
            report["equivalence_method"] = "JSON scalar types and values, all object keys, exact array order; no excluded fields"
            report["equivalent"] = exact_json_equal(baseline["oracle"], report["oracle"])
            report["different_surfaces"] = [name for name in baseline["oracle"]
                if not exact_json_equal(baseline["oracle"][name], report["oracle"].get(name))]
        target.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        if (not report["data_unchanged"] or report.get("equivalent") is False
                or report.get("concurrent_oracle_equivalent") is False or report["provider_http_attempts"]):
            raise AssertionError("Data preservation or behavioral equivalence failed; inspect evidence")
    finally:
        engine.dispose()
        cleanup = create_engine(raw)
        with cleanup.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        cleanup.dispose()


if __name__ == "__main__":
    main()
