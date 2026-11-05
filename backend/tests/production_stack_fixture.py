"""Explicit, invented fixture for an isolated production-image rehearsal.

Mount this file into the one-off provision/check container; never ship tests in
the runtime image. No application lifespan, provider client, or development DB.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

REVISION = "20261022_05"
DATABASES = {"proppulse_test_stage3", "proppulse_test_stage3_restore"}
ACKNOWLEDGEMENT = "invented-disposable-stage3-only"


def fixture_id(number):
    return str(UUID(int=number))


def target_url(value, *, allow_restore_bootstrap=False):
    if os.environ.get("PROPPULSE_STAGE3_FIXTURE_ACK") != ACKNOWLEDGEMENT:
        raise RuntimeError("Explicit disposable fixture acknowledgement required")
    if any(key.upper().startswith("PG") for key in os.environ):
        raise RuntimeError("Ambient libpq routing settings forbidden")
    try:
        target = make_url(value)
    except Exception:
        raise RuntimeError("Explicit isolated Stage 3 database required") from None
    if (target.get_backend_name() != "postgresql"
            or target.host not in {"pp-stage3-db", "pp-stage3-restore-db", "127.0.0.1", "localhost"}
            or target.database not in DATABASES or target.query
            or target.username not in {"pp_stage3_owner", "pp_stage3_app"}
            or (target.host == "pp-stage3-restore-db" and target.database != "proppulse_test_stage3_restore"
                and not (allow_restore_bootstrap and target.database == "proppulse_test_stage3"))
            or (target.host in {"127.0.0.1", "localhost"} and target.port in {None, 5432})):
        raise RuntimeError("Refusing non-fixture database target")
    return target


def verify_physical_target(connection, target):
    database, role = connection.execute(text("SELECT current_database(), current_user")).one()
    if database != target.database or role != target.username:
        raise RuntimeError("Effective database identity differs from explicit fixture target")


def fingerprint(engine):
    """Hash actual persisted rows, including user selections, without outputting them."""
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        tables = sorted(inspect(connection).get_table_names(schema="public"))
        result = {}
        for name in tables:
            # Names come only from reflected SQL identifiers and are quoted by
            # the dialect; no request text is interpolated into SQL.
            quoted = connection.dialect.identifier_preparer.quote(name)
            rows = connection.execute(text("SELECT row_to_json(t)::text FROM public." + quoted + " AS t")).scalars().all()
            normalized = sorted(json.dumps(json.loads(row), sort_keys=True, separators=(",", ":")) for row in rows)
            result[name] = {"rows": len(rows), "sha256": hashlib.sha256("\n".join(normalized).encode()).hexdigest()}
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        if revision != [REVISION]:
            raise RuntimeError("Unexpected fixture migration revision")
        return {"revision": REVISION, "tables": result}


def bootstrap(engine, target):
    if target.username != "pp_stage3_owner" or target.database != "proppulse_test_stage3":
        raise RuntimeError("Only the fixture owner may bootstrap the source fixture database")
    with engine.connect() as connection:
        if inspect(connection).get_table_names(schema="public"):
            raise RuntimeError("Bootstrap requires an empty disposable database")
    from alembic import command
    from alembic.config import Config
    from app import models as m
    from app.auth import hash_password
    from app.services.game_log_fields import provider_season
    config = Config(str(Path.cwd() / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, REVISION)
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    future = now + timedelta(days=2)
    with Session(engine) as db, db.begin():
        for number, start in ((100, future), (103, future + timedelta(days=1))):
            db.add(m.Event(id=fixture_id(number), provider="the_odds_api", sport_key="basketball_nba",
                provider_event_id=f"fixture-stack-{number}", home_team="Fixture Stack Home",
                away_team="Fixture Stack Away", scheduled_start_at=start))
        db.add(m.Player(id=fixture_id(200), name="Fixture Stack Player", team="Fixture Stack Away",
            team_abbr="FIX", sport="NBA", position="G"))
        db.add(m.User(id=fixture_id(400), email="stack-baseline@example.invalid",
            username="Invented fixture baseline", hashed_password=hash_password(secrets.token_urlsafe(24)),
            fav_sports=["NBA"], fav_players=[fixture_id(200)], fav_prop_types=["points"]))
        db.flush()
        for number, event, line in ((300, 100, 20.5), (301, 100, 21.5), (311, 103, 20.5)):
            db.add(m.Prop(id=fixture_id(number), player_id=fixture_id(200), event_id=fixture_id(event),
                prop_type="points", line=line, line_24h_ago=line - 1, sportsbook="FanDuel",
                odds_sport_key="basketball_nba", odds_event_id=f"fixture-stack-{event}",
                game_time=future if event == 100 else future + timedelta(days=1),
                opponent="Fixture Stack Home", is_home=False, is_active=True, popularity_count=0))
        db.add(m.Slip(id=fixture_id(401), user_id=fixture_id(400), status="open"))
        db.flush()
        for number, book, line, over, under, age in (
                (300, "FanDuel", 20.5, -110, -115, 0),
                (300, "DraftKings", 20.5, -105, -120, 0),
                (300, "BetMGM", 21.5, 120, -140, 0),
                (301, "FanDuel", 21.5, -102, -118, 0),
                (311, "FanDuel", 20.5, -110, -115, 8)):
            db.add(m.PropBook(prop_id=fixture_id(number), sportsbook=book, line=line,
                over_odds=over, under_odds=under, provider_observed_at=now - timedelta(hours=age),
                ingested_at=now, updated_at=now))
        db.add(m.PropBookSnapshot(id=fixture_id(450), prop_id=fixture_id(300), sportsbook="FanDuel",
            line=19.5, over_odds=-105, under_odds=-120, captured_at=now - timedelta(hours=2)))
        db.add(m.SavedProp(id=fixture_id(451), user_id=fixture_id(400), prop_id=fixture_id(300),
            sportsbook="FanDuel", line=20.5, side="under", original_odds=-115, original_observed_at=now))
        db.add(m.SlipItem(id=fixture_id(452), slip_id=fixture_id(401), prop_id=fixture_id(300),
            sportsbook="FanDuel", line=20.5, side="under", original_odds=-115, original_observed_at=now))
        db.add(m.FatigueScore(id=fixture_id(453), player_id=fixture_id(200), fatigue_score=.2,
            workload_score=.2, risk_flags=[], shap_reasons=["Invented isolated stack fixture"]))
        season = provider_season("NBA", future)
        for number in range(15):
            db.add(m.PlayerGameLog(id=fixture_id(500 + number), player_id=fixture_id(200), sport="NBA",
                external_game_id=f"fixture-stack-history-{number}", game_date=now - timedelta(days=number + 1),
                opponent="Fixture Historical Opponent", is_home=False, source="espn_nba",
                stats={"points": 18 + number % 9, "minutes": 30, "season": season,
                       "fixture": "invented-disposable-stage3-only"}))
    return {"fixture": "invented only", "ids": {"player": fixture_id(200), "event": fixture_id(100),
        "active_prop": fixture_id(300), "second_line_prop": fixture_id(301), "expired_prop": fixture_id(311)},
        "observed_at": now.isoformat() + "Z", "fingerprint": fingerprint(engine)}


def verify_app_role(engine, target):
    if target.username != "pp_stage3_app":
        raise RuntimeError("Application-role verification requires the app login")
    from app.services.schema_readiness import validate_database
    result = {}
    with engine.connect() as connection:
        row = connection.execute(text("SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
        if any(row):
            raise RuntimeError("Application role has excessive role attributes")
        memberships = connection.execute(text("SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)")).scalar_one()
        owned = connection.execute(text("SELECT count(*) FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) AND relnamespace='public'::regnamespace")).scalar_one()
        if memberships or owned:
            raise RuntimeError("Application role must have no inherited membership or owned objects")
        validate_database(connection)
        result.update(role_attributes="least_privilege", migration_owner_separated=True, readiness_schema="valid")
        for label, statement in {
            "create_table": "CREATE TABLE public.fixture_forbidden_ddl (id integer)",
            "create_schema": "CREATE SCHEMA fixture_forbidden_schema",
            "alter_table": "ALTER TABLE users ADD COLUMN fixture_forbidden integer",
            "create_role": "CREATE ROLE fixture_forbidden_role",
            "delete_provider_data": "DELETE FROM prop_books WHERE false",
        }.items():
            savepoint = connection.begin_nested()
            try:
                connection.execute(text(statement))
            except Exception as exc:
                savepoint.rollback()
                if getattr(getattr(exc, "orig", None), "pgcode", None) != "42501":
                    raise RuntimeError("Unexpected privilege-check error") from None
                result[label] = "denied"
            else:
                savepoint.rollback()
                raise RuntimeError("Forbidden application privilege succeeded: " + label)
    return result


def main():
    sys.path.insert(0, str(Path.cwd()))
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("bootstrap", "fingerprint", "verify-app-role"))
    args = parser.parse_args()
    target = target_url(os.environ.get("PROPPULSE_TEST_POSTGRES_URL", ""),
        allow_restore_bootstrap=args.action == "bootstrap")
    os.environ.update(DATABASE_URL=target.render_as_string(hide_password=False),
        ENVIRONMENT="test", LIVE_REFRESH_ENABLED="false", THE_ODDS_API_KEY="", BALLDONTLIE_API_KEY="")
    engine = create_engine(target, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            verify_physical_target(connection, target)
        action = {"bootstrap": bootstrap, "verify-app-role": verify_app_role}.get(args.action)
        result = action(engine, target) if action else fingerprint(engine)
        print(json.dumps(result, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
