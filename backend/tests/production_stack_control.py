"""Local-only production rehearsal control; generated secrets/evidence are ignored.

Run from repository root with the existing Python environment. This helper only
owns the explicitly labelled pp-stage3-* containers/networks, never development.
Build the backend image and bootstrap its fixture separately before start-api.
"""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "backend/data/odds_runs/security-stage3"
LABEL = "proppulse.task=security-stage3"
NETWORK = "pp-stage3-private"


def docker(*args, data=None):
    endpoint = "npipe:////./pipe/docker_engine" if os.name == "nt" else "unix:///var/run/docker.sock"
    result = subprocess.run(["docker", "--host", endpoint, *args], input=data,
        capture_output=True, text=True, timeout=300)
    if result.returncode:
        # Do not interpolate argv, SQL or environment values in exceptions.
        detail = result.stderr
        if (STATE / "secrets.json").exists():
            for value in json.loads((STATE / "secrets.json").read_text()).values():
                detail = detail.replace(value, "<redacted>")
        (STATE / "docker-error.log").write_text(detail, encoding="utf-8")
        raise RuntimeError("Local Docker operation failed; inspect private evidence")
    return (result.stdout + (result.stderr if args[0] == "logs" else "")).strip()


def owned(kind, name):
    state = json.loads(docker(kind, "inspect", name))[0]
    labels = state.get("Labels", {}) if kind == "network" else state["Config"].get("Labels", {})
    if labels.get("proppulse.task") != "security-stage3":
        raise RuntimeError("Refusing an unowned local resource")
    return state


def write_env(name, values):
    path = STATE / name
    path.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8")


def prepare():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    STATE.mkdir(parents=True, exist_ok=True)
    if (STATE / "secrets.json").exists():
        raise RuntimeError("Private run state already exists; do not overwrite it")
    values = {name: secrets.token_urlsafe(48) for name in ("admin", "owner", "app", "jwt")}
    (STATE / "secrets.json").write_text(json.dumps(values), encoding="utf-8")
    write_env("db.env", {"POSTGRES_USER": "stage3_admin", "POSTGRES_PASSWORD": values["admin"], "POSTGRES_DB": "postgres"})
    write_env("roles.env", {"PP_OWNER_PASSWORD": values["owner"], "PP_APP_PASSWORD": values["app"]})
    role_sql = ""
    for role, variable in (("pp_stage3_owner", "owner_password"), ("pp_stage3_app", "app_password")):
        role_sql += f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD :'{variable}';\n"
    for database in ("proppulse_test_stage3", "proppulse_test_stage3_restore"):
        role_sql += f"CREATE DATABASE {database} OWNER pp_stage3_owner;\nREVOKE ALL ON DATABASE {database} FROM PUBLIC;\nGRANT CONNECT ON DATABASE {database} TO pp_stage3_owner, pp_stage3_app;\n"
    (STATE / "provision-admin.sql").write_text(role_sql)
    (STATE / "grant-app.sql").write_text("REVOKE ALL ON SCHEMA public FROM PUBLIC;\n"
        "GRANT USAGE ON SCHEMA public TO pp_stage3_app;\n"
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pp_stage3_app;\n"
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO pp_stage3_app;\n"
        "GRANT INSERT, UPDATE, DELETE ON users, interactions, saved_props, slips, slip_items TO pp_stage3_app;\n"
        "GRANT UPDATE (popularity_count) ON props TO pp_stage3_app;\n")
    common = {"PROPPULSE_STAGE3_FIXTURE_ACK": "invented-disposable-stage3-only"}
    for filename, role, key, database in (
        ("owner.env", "pp_stage3_owner", "owner", "proppulse_test_stage3"),
        ("app-check.env", "pp_stage3_app", "app", "proppulse_test_stage3"),
        ("restore-owner.env", "pp_stage3_owner", "owner", "proppulse_test_stage3_restore")):
        write_env(filename, dict(common, PROPPULSE_TEST_POSTGRES_URL=f"postgresql://{role}:{values[key]}@pp-stage3-db:5432/{database}"))
    write_env("api.env", {"DATABASE_URL": f"postgresql://pp_stage3_app:{values['app']}@pp-stage3-db:5432/proppulse_test_stage3",
        "ENVIRONMENT": "production", "JWT_SECRET": values["jwt"], "JWT_EXPIRE_MINUTES": "120",
        "AUTH_COOKIE_SAMESITE": "lax", "GATEWAY_RATE_LIMIT_ENABLED": "true",
        "CORS_ORIGINS": '["https://app.proppulse.test:3443"]', "LIVE_REFRESH_ENABLED": "false",
        "THE_ODDS_API_KEY": "", "BALLDONTLIE_API_KEY": "", "PYTHONDONTWRITEBYTECODE": "1"})
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable PropPulse local test")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2)).add_extension(x509.SubjectAlternativeName([
            x509.DNSName("app.proppulse.test"), x509.DNSName("api.proppulse.test")]), critical=False)
        .sign(key, hashes.SHA256()))
    (STATE / "test-cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (STATE / "test-key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    print("Disposable secrets and certificate generated privately; no values printed")


def start_networks():
    docker("network", "create", "--internal", "--label", LABEL, NETWORK)
    docker("network", "create", "--label", LABEL, "pp-stage3-edge")
    print("Disposable private and gateway-edge networks created")


def start_db(image):
    owned("network", NETWORK)
    docker("run", "-d", "--name", "pp-stage3-db", "--label", LABEL, "--network", NETWORK,
        "--user", "70:70", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", "768m", "--cpus", "2", "--pids-limit", "200",
        "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=512m,uid=70,gid=70,mode=0700",
        "--tmpfs", "/var/run/postgresql:rw,noexec,nosuid,size=16m,uid=70,gid=70,mode=0775",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,mode=1777",
        "--env-file", str(STATE / "db.env"), image,
        "-c", "log_statement=none", "-c", "log_min_error_statement=panic")
    for _ in range(30):
        try:
            docker("exec", "pp-stage3-db", "pg_isready", "-U", "stage3_admin")
            return
        except RuntimeError:
            time.sleep(0.5)
    raise RuntimeError("Disposable database not ready")


def provision():
    owned("container", "pp-stage3-db")
    sql = "\\getenv owner_password PP_OWNER_PASSWORD\n\\getenv app_password PP_APP_PASSWORD\n"
    sql += (STATE / "provision-admin.sql").read_text()
    docker("exec", "-i", "--env-file", str(STATE / "roles.env"), "pp-stage3-db",
        "psql", "-U", "stage3_admin", "-d", "postgres", "-v", "ON_ERROR_STOP=1", data=sql)
    # NOINHERIT owner roles must own the schema explicitly, rather than relying
    # on PostgreSQL's implicit pg_database_owner public-schema privileges.
    for database in ("proppulse_test_stage3", "proppulse_test_stage3_restore"):
        docker("exec", "pp-stage3-db", "psql", "-U", "stage3_admin", "-d", database,
            "-v", "ON_ERROR_STOP=1", "-c", "ALTER SCHEMA public OWNER TO pp_stage3_owner")
    print("Disposable roles/databases created; no application superuser")


def start_api(image):
    network = owned("network", NETWORK)
    subnet = ipaddress.ip_network(network["IPAM"]["Config"][0]["Subnet"])
    gateway = str(subnet.network_address + 10)
    (STATE / "gateway-ip.txt").write_text(gateway)
    for suffix in ("a", "b"):
        docker("run", "-d", "--name", f"pp-stage3-api-{suffix}", "--label", LABEL,
            "--network", NETWORK, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "768m", "--cpus", "1", "--pids-limit", "128",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,uid=10001,gid=10001",
            "--tmpfs", "/app/data:rw,noexec,nosuid,size=16m,uid=10001,gid=10001",
            "--env-file", str(STATE / "api.env"), image,
            "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
            "--proxy-headers", "--forwarded-allow-ips", gateway, "--no-access-log")
    print("Two non-root API replicas started privately; only reserved gateway IP trusted")


def start_gateway(image):
    owned("network", NETWORK)
    owned("network", "pp-stage3-edge")
    gateway = (STATE / "gateway-ip.txt").read_text()
    docker("create", "--name", "pp-stage3-gateway", "--label", LABEL, "--network", NETWORK, "--ip", gateway,
        "--publish", "127.0.0.1:3443:443", "--read-only", "--security-opt", "no-new-privileges",
        "--memory", "128m", "--cpus", "1", "--pids-limit", "64", "--tmpfs", "/tmp:rw,nosuid,size=64m",
        "--mount", f"type=bind,source={ROOT / 'backend/tests/production_gateway.conf'},target=/etc/nginx/nginx.conf,readonly",
        "--mount", f"type=bind,source={STATE / 'test-cert.pem'},target=/certs/test-cert.pem,readonly",
        "--mount", f"type=bind,source={STATE / 'test-key.pem'},target=/certs/test-key.pem,readonly",
        "--entrypoint", "nginx", image, "-g", "daemon off;")
    docker("network", "connect", "pp-stage3-edge", "pp-stage3-gateway")
    docker("start", "pp-stage3-gateway")
    print("HTTPS gateway started on loopback3443; API and DB have no published ports")


def cleanup():
    # Inspect presence, but only remove exact named resources owned by this task.
    # A failed/partial startup must not prevent cleanup of the remaining stack.
    existing_containers = set(docker("container", "ls", "--all", "--format", "{{.Names}}").splitlines())
    existing_networks = set(docker("network", "ls", "--format", "{{.Name}}").splitlines())
    containers = [name for name in ("pp-stage3-gateway", "pp-stage3-api-a", "pp-stage3-api-b",
        "pp-stage3-restore-db", "pp-stage3-db") if name in existing_containers]
    networks = [name for name in ("pp-stage3-edge", NETWORK) if name in existing_networks]
    # Validate every present candidate before the first destructive operation.
    for kind, names in (("container", containers), ("network", networks)):
        for name in names:
            owned(kind, name)
    for name in containers:
        docker("rm", "-f", name)
    for name in networks:
        docker("network", "rm", name)
    print("Only task-owned disposable containers and networks removed; evidence retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "start-networks", "start-db", "provision", "start-api", "start-gateway", "cleanup"))
    parser.add_argument("--image", default="proppulse-backend:hardened")
    parser.add_argument("--postgres-image", default="proppulse-postgres:nonroot")
    parser.add_argument("--gateway-image", default="proppulse-security-stage3-gateway:final")
    args = parser.parse_args()
    action = {"prepare": prepare, "start-networks": start_networks, "start-db": lambda: start_db(args.postgres_image), "provision": provision,
              "start-api": lambda: start_api(args.image), "start-gateway": lambda: start_gateway(args.gateway_image), "cleanup": cleanup}[args.action]
    action()
