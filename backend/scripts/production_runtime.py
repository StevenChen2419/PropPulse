"""Explicit production jobs and secret-file startup; never refresh providers."""
import ipaddress
import os
from pathlib import Path
import re
import sys


def secret(name):
    value = Path("/run/secrets", name).read_text().strip()
    if not value or "\n" in value or "\r" in value:
        raise RuntimeError("Invalid secret file: " + name)
    return value


def database_name():
    name = os.environ.get("PG_DATABASE", "proppulse")
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,62}", name):
        raise RuntimeError("Invalid database name")
    return name


def bootstrap():
    # Only this separately invoked job receives the cluster administrator secret.
    import psycopg2
    from psycopg2 import sql
    database = database_name()
    connection = psycopg2.connect(host="db", dbname="postgres", user="postgres",
                                 password=secret("db_admin_password"))
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            for role, filename in (("pp_owner", "db_owner_password"), ("pp_app", "db_app_password")):
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
                if cursor.fetchone():
                    raise RuntimeError("Bootstrap requires new roles; existing credentials are never reset")
            for role, filename in (("pp_owner", "db_owner_password"), ("pp_app", "db_app_password")):
                cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %s").format(sql.Identifier(role)), (secret(filename),))
            cursor.execute(sql.SQL("CREATE DATABASE {} OWNER pp_owner").format(sql.Identifier(database)))
            cursor.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO pp_owner, pp_app").format(sql.Identifier(database)))
    finally:
        connection.close()
    with psycopg2.connect(host="db", dbname=database, user="postgres",
                         password=secret("db_admin_password")) as connection:
        with connection.cursor() as cursor:
            cursor.execute("ALTER SCHEMA public OWNER TO pp_owner")
    print("Database roles provisioned; no credentials printed", flush=True)


def configure(mode):
    from sqlalchemy.engine import make_url
    value = secret("database_url")
    target = make_url(value)
    role = "pp_owner" if mode == "migrate" else "pp_app"
    if (target.get_backend_name() != "postgresql" or target.host != "db"
            or target.port != 5432 or target.database != database_name()
            or target.username != role or target.query):
        raise RuntimeError("Unexpected production database target")
    os.environ["DATABASE_URL"] = value
    os.environ["JWT_SECRET"] = secret("jwt_secret")
    os.environ["LIVE_REFRESH_ENABLED"] = "false"
    os.environ["THE_ODDS_API_KEY"] = ""
    os.environ["BALLDONTLIE_API_KEY"] = ""
    from app.config import settings
    if not settings.production or settings.configuration_errors():
        raise RuntimeError("Invalid production configuration")
    return target


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    if mode == "bootstrap":
        bootstrap()
        return
    if mode not in {"migrate", "serve"}:
        raise RuntimeError("Choose the explicit bootstrap, migrate or serve operation")
    target = configure(mode)
    if mode == "migrate":
        from sqlalchemy import create_engine, text
        from alembic import command
        from alembic.config import Config
        engine = create_engine(target)
        with engine.begin() as connection:
            if connection.execute(text("SELECT current_database(), current_user")).one() != (database_name(), "pp_owner"):
                raise RuntimeError("Physical database target mismatch")
            config = Config("/app/alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "20261022_05")
            connection.execute(text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
            connection.execute(text("GRANT USAGE ON SCHEMA public TO pp_app"))
            connection.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO pp_app"))
            connection.execute(text("GRANT INSERT, UPDATE, DELETE ON users, interactions, saved_props, slips, slip_items TO pp_app"))
            connection.execute(text("GRANT UPDATE (popularity_count) ON props TO pp_app"))
        engine.dispose()
        print("Migration and restricted application grants complete", flush=True)
        return
    gateway = str(ipaddress.ip_address(os.environ["TRUSTED_GATEWAY_IP"]))
    if ipaddress.ip_address(gateway).is_unspecified:
        raise RuntimeError("An exact gateway address is required")
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "0.0.0.0", "--port", "8000", "--workers", "1",
        "--proxy-headers", "--forwarded-allow-ips", gateway, "--no-access-log"])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Driver exceptions can contain SQL, passwords or connection URLs.
        print("Production operation failed; check configuration and private database health", file=sys.stderr)
        sys.exit(1)
