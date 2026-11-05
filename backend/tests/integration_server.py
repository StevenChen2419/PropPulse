"""Disposable PostgreSQL fixture + actual API for browser integration only.

Run from backend with explicit PROPPULSE_TEST_POSTGRES_URL. Connection, refresh,
and provider settings are overridden before importing the app; the replacement
settings instance disables env-file loading. Never deploy this file.
Synthetic fixtures and optional explicitly authorized normalized NBA observations
are created only in an empty proppulse_test_ database.
"""
import hashlib
import http.client
import os
import re
from pathlib import Path
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, inspect, text, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def fixture_id(number):
    return str(UUID(int=number))


def integration_target(value):
    """Validate the effective target before any engine or application import."""
    if any(key.upper().startswith("PG") for key in os.environ):
        raise RuntimeError("Ambient libpq settings are forbidden for browser fixtures")
    try:
        target = make_url(value)
    except Exception:
        raise RuntimeError("Explicit loopback proppulse_test_ PostgreSQL required") from None
    if (target.get_backend_name() != "postgresql" or target.host not in ("127.0.0.1", "localhost")
            or target.query
            or not re.fullmatch(r"proppulse_test_[a-z0-9_]+", target.database or "")):
        raise RuntimeError("Explicit loopback proppulse_test_ PostgreSQL required")
    return target


def main():
    target = integration_target(os.environ.get("PROPPULSE_TEST_POSTGRES_URL", ""))
    os.environ.update(DATABASE_URL=target.render_as_string(hide_password=False),
                      LIVE_REFRESH_ENABLED="false", JWT_SECRET="isolated-browser-test-only",
                      THE_ODDS_API_KEY="", BALLDONTLIE_API_KEY="")
    import app.config
    app.config.settings = app.config.Settings(_env_file=None)
    from app.database import Base, get_db
    from app.models import Event, Player, Prop, PropBook, PropBookSnapshot, PlayerGameLog, User, SavedProp, Slip, SlipItem
    from app.auth import create_token
    from app.services.game_identity_service import event_context
    from app.services.game_log_fields import provider_season
    admin = create_engine(target)
    Session = sessionmaker(bind=admin)
    # Validate the physical libpq connection before even schema inspection or
    # fixture DDL. URL validation alone does not prove effective routing.
    from app.services.nba_evidence_service import _test_target
    with Session() as check_db:
        _test_target(check_db)
    if inspect(admin).get_table_names():
        raise RuntimeError("Integration runner requires an empty disposable database")
    Base.metadata.create_all(admin)
    # Exercise the existing append-only guards/namespace in this empty disposable
    # database, pinned to the reviewed milestone rather than a moving head.
    from alembic import command
    from alembic.config import Config
    migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with admin.begin() as connection:
        migration.attributes["connection"] = connection
        command.upgrade(migration, "20261018_04")
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    ids = {"event": fixture_id(100), "second_event": fixture_id(101),
           "empty_event": fixture_id(102), "expired_event": fixture_id(103),
           "player": fixture_id(200), "second_player": fixture_id(201),
           "no_history_player": fixture_id(202), "prop": fixture_id(300),
           "second_prop": fixture_id(305), "other_event_prop": fixture_id(310),
           "expired_prop": fixture_id(311), "no_history_prop": fixture_id(312)}
    with Session.begin() as db:
        events = []
        for n, key in enumerate(("event", "second_event", "empty_event", "expired_event")):
            ev = Event(id=ids[key], provider="the_odds_api", sport_key="basketball_nba",
                       provider_event_id=f"fixture-integration-{n}", away_team="Fixture Away",
                       home_team="Fixture Home", scheduled_start_at=now + timedelta(days=2+n))
            events.append(ev)
            db.add(ev)
        players = []
        for n, key in enumerate(("player", "second_player", "no_history_player")):
            player = Player(id=ids[key], name=("Fixture Player", "Fixture Teammate", "Fixture No History")[n],
                            team="Fixture Away" if n == 0 else "Fixture Home", team_abbr="FIX", sport="NBA")
            players.append(player)
            db.add(player)
        db.flush()
        def prop(number, player, ev, market="points", expired=False, linked=True):
            p = Prop(id=fixture_id(number), player_id=player.id, event_id=ev.id if linked else None, prop_type=market,
                     line=20.5, line_24h_ago=19.5, sportsbook="FanDuel", game_time=ev.scheduled_start_at,
                     odds_sport_key=ev.sport_key, odds_event_id=ev.provider_event_id,
                     opponent="Fixture Home", is_home=False)
            db.add(p)
            db.flush()
            db.add(PropBook(prop_id=p.id, sportsbook="FanDuel", line=20.5, over_odds=-110,
                            under_odds=-115, provider_observed_at=now-timedelta(hours=7) if expired else now,
                            ingested_at=now, updated_at=now))
            db.add(PropBookSnapshot(prop_id=p.id, sportsbook="FanDuel", line=19.5,
                                   over_odds=-105, under_odds=-120, captured_at=now-timedelta(hours=2)))
            return p
        for n, player in enumerate(players[:2]):
            for m, market in enumerate(("points", "assists", "rebounds", "threes", "blocks")):
                prop(300+n*5+m, player, events[0], market)
        prop(310, players[0], events[1])
        prop(311, players[0], events[3], expired=True)
        prop(312, players[2], events[1])
        # Two namespaces with the exact same old key make legacy lookup ambiguous.
        for n in range(2):
            p = prop(320+n, players[0], events[0], linked=False)
            p.odds_event_id = f"legacy-{n}"
        season = provider_season("NBA", events[0].scheduled_start_at)
        for player in players[:2]:
            for n in range(12):
                db.add(PlayerGameLog(player_id=player.id, sport="NBA", source="espn_nba",
                    external_game_id=f"synthetic-{n}", game_date=now-timedelta(days=n+1),
                    opponent="Fixture Opponent", is_home=True,
                    stats={"points": 30, "assists": 25, "rebounds": 24, "threes": 23,
                           "blocks": 22, "minutes": 32, "season": season}))
        # New evidence fixtures are persisted through the actual offline adapter,
        # never injected into the API/calculator or inferred from legacy logs.
        from participation_fixture import participation_manifest
        from app.services.nba_evidence_service import reconcile_fixture
        ids.update(verified_player_id=fixture_id(210), partial_player_id=fixture_id(211),
                   verified_event_id=fixture_id(110), rested_event_id=fixture_id(111),
                   partial_event_id=fixture_id(112), verified_prop_id=fixture_id(350),
                   rested_prop_id=fixture_id(351), partial_prop_id=fixture_id(352))
        manifest, reference, rested_reference = participation_manifest(now,
            confirmed_player_id=ids["verified_player_id"], partial_player_id=ids["partial_player_id"])
        for key, label, team in (("verified_player_id", "Fixture Confirmed Participation", "fixture-confirmed-team"),
                                  ("partial_player_id", "Fixture Partial Participation", "fixture-partial-team")):
            db.add(Player(id=ids[key], name=label, team=team, team_abbr="EVD", sport="NBA"))
        for event_key, prop_key, player_key, at, team in (
                ("verified_event_id", "verified_prop_id", "verified_player_id", reference, "fixture-confirmed-team"),
                ("rested_event_id", "rested_prop_id", "verified_player_id", rested_reference, "fixture-confirmed-team"),
                ("partial_event_id", "partial_prop_id", "partial_player_id", reference, "fixture-partial-team")):
            db.add(Event(id=ids[event_key], provider="the_odds_api", sport_key="basketball_nba",
                         provider_event_id=f"fixture-evidence-{event_key}", away_team=team,
                         home_team="fixture-opponent", scheduled_start_at=at))
            db.flush()
            db.add(Prop(id=ids[prop_key], player_id=ids[player_key], event_id=ids[event_key],
                        prop_type="points", line=20.5, sportsbook="FanDuel", game_time=at,
                        odds_sport_key="basketball_nba", odds_event_id=f"fixture-evidence-{event_key}",
                        opponent="fixture-opponent", is_home=False))
        db.flush()
        arguments = {"sport": "NBA", "start_date": manifest["date_start"], "end_date": manifest["date_end"],
                     "team_ids": manifest["team_ids"], "now": now.replace(tzinfo=timezone.utc)}
        dry = reconcile_fixture(db, manifest, **arguments)
        written = reconcile_fixture(db, manifest, **arguments, write=True, expected_digest=dry["digest"])
        assert written["inserted"] == len(manifest["records"])
        ids["nba_rest_demo"] = []
        # Only an explicitly supplied, already-normalized authorized collection
        # may populate these separate actual-source diagnostic identities.
        if os.environ.get("PROPPULSE_NBA_STATISTICS_DEMO_FILE"):
            if os.environ.get("PROPPULSE_NBA_DEMO_NORMALIZED_FILE"):
                raise RuntimeError("Choose one actual-source demo artifact")
            from nba_real_statistics_demo import seed_real_statistics_demo
            ids["nba_real_statistics_demo"] = seed_real_statistics_demo(
                db, os.environ["PROPPULSE_NBA_STATISTICS_DEMO_FILE"])
        elif os.environ.get("PROPPULSE_NBA_DEMO_NORMALIZED_FILE"):
            from nba_real_rest_demo import seed_real_demo
            ids["nba_real_rest_demo"] = seed_real_demo(db, os.environ["PROPPULSE_NBA_DEMO_NORMALIZED_FILE"])
        else:
            # Never mix invented same-team/date games with real observations:
            # the evidence service correctly quarantines conflicting identities.
            from nba_rest_demo_fixture import seed_demo
            ids["nba_rest_demo"] = seed_demo(db)
        from nba_statistics_fixture import seed_statistics
        ids["nba_statistics_demo"] = seed_statistics(db, now.replace(tzinfo=timezone.utc))
        statistics_event = Event(id="5b000000-0000-4000-8000-000000000002", provider="fixture_5b",
            sport_key="basketball_nba", provider_event_id="invented-statistics-reference",
            home_team="Boston Celtics", away_team="Orlando Magic", scheduled_start_at=now+timedelta(days=2))
        db.add(statistics_event)
        db.flush()
        db.add(Prop(id="5b000000-0000-4000-8000-000000000003",
            player_id=ids["nba_statistics_demo"]["player_id"], event_id=statistics_event.id,
            prop_type="points", line=20.5, sportsbook="Fixture unavailable", is_active=False))
        ids["nba_statistics_demo"].update(prop_id="5b000000-0000-4000-8000-000000000003",
                                         event_id=statistics_event.id)
        from nba_matchup_fixture import seed_matchup
        ids["nba_matchup_demo"] = seed_matchup(db, now.replace(tzinfo=timezone.utc))
        user = User(id=fixture_id(400), email="integration@example.invalid", hashed_password="unused",
                    fav_players=[ids["player"]])
        db.add(user)
        db.flush()
        slip = Slip(id=fixture_id(401), user_id=user.id)
        db.add(slip)
        db.flush()
        db.add_all([SavedProp(user_id=user.id, prop_id=ids["prop"]),
                    SlipItem(slip_id=slip.id, prop_id=ids["prop"], side="under", sportsbook="FanDuel", line=19.5)])
        ids.update(token=create_token(user.id), legacy=event_context(events[0])["game_key"])
    ids.update(event_id=ids["event"], second_event_id=ids["second_event"],
               empty_event_id=ids["empty_event"], player_id=ids["player"],
               second_player_id=ids["second_player"], prop_id=ids["prop"],
               second_player_prop_id=ids["second_prop"], other_event_prop_id=ids["other_event_prop"],
               expired_prop_id=ids["expired_prop"], missing_history_prop_id=ids["no_history_prop"],
               missing_history_player_id=ids["no_history_player"], legacy_key=ids["legacy"])
    # Browser API uses a role that PostgreSQL itself denies all DML/DDL.
    with admin.begin() as conn:
        conn.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='proppulse_browser_readonly') "
                          "THEN CREATE ROLE proppulse_browser_readonly LOGIN; END IF; END $$"))
        conn.execute(text("GRANT CONNECT ON DATABASE " + target.database + " TO proppulse_browser_readonly"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO proppulse_browser_readonly"))
        conn.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO proppulse_browser_readonly"))
        conn.execute(text("ALTER ROLE proppulse_browser_readonly SET default_transaction_read_only=on"))
    reader = create_engine(target.set(username="proppulse_browser_readonly", password=None))
    ReadSession = sessionmaker(bind=reader)
    with reader.connect() as conn:
        assert conn.execute(text("SHOW transaction_read_only")).scalar() == "on"
        try:
            conn.execute(text("UPDATE props SET line=line WHERE false"))
        except Exception as exc:
            assert getattr(exc.orig, "pgcode", None) == "25006"
        else:
            raise RuntimeError("Read-only write challenge unexpectedly succeeded")
    from app.main import app
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3199"],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    def db_dependency():
        with ReadSession() as db:
            yield db
    app.dependency_overrides[get_db] = db_dependency
    # Do not read the user's retained provider status artifacts in integration.
    import app.routers.props as props_router
    props_router.read_ingestion_status = lambda: {"source": "synthetic_integration", "sports": {}}
    attempts = []
    latencies = []
    query_counts = []
    request_queries = ContextVar("integration_query_count", default=None)
    @event.listens_for(reader, "before_cursor_execute")
    def query_observer(*args):
        count = request_queries.get()
        if count is not None:
            count[0] += 1
    @app.middleware("http")
    async def measure(request, call_next):
        start, count = time.perf_counter(), [0]
        token = request_queries.set(count)
        try:
            response = await call_next(request)
        finally:
            request_queries.reset(token)
        if not request.url.path.startswith("/__test__"):
            latencies.append({"path": request.url.path, "ms": round((time.perf_counter()-start)*1000, 2)})
            query_counts.append({"path": request.url.path, "queries": count[0]})
            del latencies[:-10000]
            del query_counts[:-10000]
        return response
    def snapshot():
        result = {}
        with admin.connect() as conn:
            for name in sorted(inspect(admin).get_table_names()):
                rows = conn.execute(text('SELECT row_to_json(t)::text FROM "'+name+'" t ORDER BY row_to_json(t)::text')).scalars().all()
                result[name] = {"count": len(rows), "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest()}
        return result
    baseline = snapshot()
    @app.get("/__test__/manifest")
    def manifest():
        return ids
    @app.get("/__test__/snapshot")
    @app.get("/__test__/preservation")
    def preservation():
        after = snapshot()
        return {"before": baseline, "after": after, "unchanged": baseline == after,
                "provider_http_attempts": len(attempts), "latencies": latencies, "query_counts": query_counts}
    @app.post("/__test__/scenario")
    def scenario(body: dict):
        from fastapi import HTTPException
        stage = body.get("scenario")
        if stage not in ("moved", "expired", "baseline"):
            raise HTTPException(400, "Unknown isolated fixture stage")
        line = 21.5 if stage == "moved" else 20.5
        observed = now-timedelta(hours=7) if stage == "expired" else now
        with admin.begin() as conn:
            conn.execute(text("UPDATE props SET line=:line WHERE id=:id"), {"line": line, "id": ids["prop"]})
            conn.execute(text("UPDATE prop_books SET line=:line,provider_observed_at=:observed WHERE prop_id=:id"),
                         {"line": line, "observed": observed, "id": ids["prop"]})
        return {"prop_id": ids["prop"], "line": line, "scenario": stage}
    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Provider/external HTTP forbidden in integration server")
    async def forbidden_async(*args, **kwargs):
        return forbidden()
    import httpx
    import uvicorn
    print("Integration fixture ready; PostgreSQL read-only API; refresh disabled; HTTP blocked", flush=True)
    with patch.object(httpx.HTTPTransport, "handle_request", forbidden), \
         patch.object(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_async), \
         patch.object(http.client.HTTPConnection, "connect", forbidden):
        # Actual application/router stack; normal lifespan intentionally disabled
        # because fixture DDL is complete and no background worker may start.
        uvicorn.run(app, host="127.0.0.1", port=8000, lifespan="off", log_level="warning")


if __name__ == "__main__":
    main()
