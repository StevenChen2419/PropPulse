"""Opt-in regression for hardened images, using only new disposable resources.

No development database, provider or published port. Reuses the Stage 3 fixture
and authentication contracts. Private settings/dump/session evidence stay ignored.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "backend/data/odds_runs/container-image-remediation/pg/regression"
LABEL = "container-image-remediation"
NETWORK = "pp-image-pg-private"
DBS = ("pp-image-pg-source", "pp-image-pg-restore")
API = "pp-image-api"
ACK = "invented-disposable-stage3-only"


def run(backend, postgres):
    if STATE.exists() and any(STATE.iterdir()):
        raise RuntimeError("Private regression already exists; preserve it before a new run")
    STATE.mkdir(parents=True, exist_ok=True)
    values = {key: secrets.token_urlsafe(48) for key in ("admin", "owner", "app", "jwt", "password")}
    (STATE / "secrets.json").write_text(json.dumps(values), encoding="utf-8")
    (STATE / "proof").mkdir()
    endpoint = "npipe:////./pipe/docker_engine" if os.name == "nt" else "unix:///var/run/docker.sock"
    created = []
    network_created = False
    run_id = secrets.token_hex(12)

    def docker(*args, data=None, binary=False, check=True):
        result = subprocess.run(["docker", "--host", endpoint, *map(str, args)],
            input=data, text=not binary, capture_output=True, timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if check and result.returncode:
            detail = result.stderr.decode(errors="replace") if binary else result.stderr
            for value in values.values():
                detail = detail.replace(value, "<redacted>")
            (STATE / "error.log").write_text(detail, encoding="utf-8")
            raise RuntimeError("Disposable image regression failed; inspect private evidence")
        return result

    def envfile(name, contents):
        path = STATE / name
        path.write_text("".join(f"{key}={value}\n" for key, value in contents.items()), encoding="utf-8")
        return path

    def sql(container, database, statement, user="image_admin"):
        return docker("exec", "-i", container, "psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1",
            "-U", user, "-d", database, data=statement).stdout.strip()

    fixture = ROOT / "backend/tests/production_stack_fixture.py"
    auth = ROOT / "backend/tests/container_postgres_auth.py"

    def worker(env, action, auth_mode=False, evidence=None):
        result = docker("run", "--rm", "--label", "proppulse.task=" + LABEL,
            "--network", NETWORK, "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "128", "--memory", "768m", "--cpus", "1",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,uid=10001,gid=10001", "--env-file", env,
            "--mount", f"type=bind,source={fixture},target=/fixture/production_stack_fixture.py,readonly",
            "--mount", f"type=bind,source={auth},target=/fixture/container_postgres_auth.py,readonly",
            "--mount", f"type=bind,source={STATE / 'proof'},target=/proof",
            backend, "python", "/fixture/container_postgres_auth.py" if auth_mode else "/fixture/production_stack_fixture.py",
            *([] if auth_mode else [action]))
        report = json.loads(result.stdout)
        (STATE / ((evidence or action) + ".json")).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return report

    grants = """REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO pp_stage3_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO pp_stage3_app;
GRANT INSERT, UPDATE, DELETE ON users, interactions, saved_props, slips, slip_items TO pp_stage3_app;
GRANT UPDATE (popularity_count) ON props TO pp_stage3_app;
"""
    try:
        for name in (*DBS, API):
            if docker("container", "inspect", name, check=False).returncode == 0:
                raise RuntimeError("Disposable name already exists; refusing to adopt a container")
        if docker("network", "inspect", NETWORK, check=False).returncode == 0:
            raise RuntimeError("Disposable network already exists; refusing to adopt it")
        docker("network", "create", "--internal", "--label", "proppulse.task=" + LABEL, "--label", "proppulse.run=" + run_id, NETWORK)
        network_created = True
        db_env = envfile("postgres.env", {"POSTGRES_USER": "image_admin", "POSTGRES_PASSWORD": values["admin"], "POSTGRES_DB": "postgres"})
        owners, applications, configs = [], [], []
        for index, name in enumerate(DBS):
            host = "pp-stage3-db" if index == 0 else "pp-stage3-restore-db"
            database = "proppulse_test_stage3" if index == 0 else "proppulse_test_stage3_restore"
            created.append(name)
            docker("run", "-d", "--pull", "never", "--name", name, "--label", "proppulse.task=" + LABEL, "--label", "proppulse.run=" + run_id,
                "--network", NETWORK, "--network-alias", host, "--user", "70:70", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--memory", "512m", "--cpus", "1", "--pids-limit", "128",
                "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=512m,uid=70,gid=70,mode=0700",
                "--tmpfs", "/var/run/postgresql:rw,noexec,nosuid,size=16m,uid=70,gid=70,mode=0775",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m,mode=1777", "--env-file", db_env, postgres,
                "-c", "log_statement=none", "-c", "log_min_error_statement=panic")
            for _ in range(60):
                ready = docker("exec", name, "pg_isready", "-U", "image_admin", "-d", "postgres", check=False)
                final_process = docker("exec", name, "sh", "-c", 'test "$(readlink /proc/1/exe)" = /usr/local/bin/postgres', check=False)
                # pg_isready can see initdb's temporary server before the official
                # entrypoint execs the final PostgreSQL process.
                if ready.returncode == 0 and final_process.returncode == 0:
                    break
                time.sleep(.5)
            else:
                raise RuntimeError("Disposable PostgreSQL did not become ready")
            process = docker("exec", name, "sh", "-c", "test ! -e /usr/local/bin/gosu && readlink /proc/1/exe && grep -E '^(Uid|Gid|CapEff|NoNewPrivs):' /proc/1/status").stdout
            assert "/postgres" in process and "Uid:\t70\t70\t70\t70" in process and "CapEff:\t0000000000000000" in process and "NoNewPrivs:\t1" in process
            # Generated URL-safe values need no SQL escaping; never read user secrets.
            sql(name, "postgres", f"CREATE ROLE pp_stage3_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '{values['owner']}';\n"
                f"CREATE ROLE pp_stage3_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '{values['app']}';\n"
                f"CREATE DATABASE {database} OWNER pp_stage3_owner; REVOKE ALL ON DATABASE {database} FROM PUBLIC; GRANT CONNECT ON DATABASE {database} TO pp_stage3_owner, pp_stage3_app;")
            sql(name, database, "ALTER SCHEMA public OWNER TO pp_stage3_owner;")
            base = {"PROPPULSE_STAGE3_FIXTURE_ACK": ACK}
            owner = f"postgresql://pp_stage3_owner:{values['owner']}@{host}:5432/{database}"
            application = f"postgresql://pp_stage3_app:{values['app']}@{host}:5432/{database}"
            owners.append(envfile(f"owner-{index}.env", dict(base, PROPPULSE_TEST_POSTGRES_URL=owner)))
            applications.append(envfile(f"app-{index}.env", dict(base, PROPPULSE_TEST_POSTGRES_URL=application)))
            configs.append(envfile(f"api-{index}.env", dict(base, DATABASE_URL=application,
                ENVIRONMENT="production", JWT_SECRET=values["jwt"], JWT_EXPIRE_MINUTES="120", AUTH_COOKIE_SAMESITE="lax",
                GATEWAY_RATE_LIMIT_ENABLED="true", CORS_ORIGINS='["https://app.proppulse.test:3443"]', LIVE_REFRESH_ENABLED="false",
                THE_ODDS_API_KEY="", BALLDONTLIE_API_KEY="", PROPPULSE_IMAGE_AUTH_PASSWORD=values["password"],
                PROPPULSE_IMAGE_AUTH_MODE="source" if index == 0 else "restore")))
        worker(owners[0], "bootstrap")
        sql(DBS[0], "proppulse_test_stage3", grants, "pp_stage3_owner")
        role = worker(applications[0], "verify-app-role")
        source_auth = worker(configs[0], "source-auth", auth_mode=True)
        before = worker(owners[0], "fingerprint", evidence="source-before-backup")
        # Exercise the image's real default command, network DNS and process UID.
        created.append(API)
        docker("run", "-d", "--name", API, "--label", "proppulse.task=" + LABEL, "--label", "proppulse.run=" + run_id, "--network", NETWORK,
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--env-file", configs[0],
            "--memory", "512m", "--cpus", "1", "--pids-limit", "128",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,uid=10001,gid=10001", backend)
        probe = "import json,urllib.request,socket; assert socket.getaddrinfo('pp-stage3-db',5432); print(json.dumps({p:json.load(urllib.request.urlopen('http://pp-image-api:8000'+p,timeout=5)) for p in ['/health','/ready']}))"
        for _ in range(30):
            response = docker("run", "--rm", "--label", "proppulse.task=" + LABEL, "--network", NETWORK,
                "--read-only", backend, "python", "-c", probe, check=False)
            if response.returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError("Final runtime's default API command did not become ready")
        api_report = json.loads(response.stdout)
        assert api_report == {"/health": {"status": "ok"}, "/ready": {"status": "ready"}}
        process = json.loads(docker("exec", API, "python", "-c", "import json,os; print(json.dumps({'uid':os.getuid(),'exe':os.readlink('/proc/1/exe')}))").stdout)
        assert process["uid"] == 10001 and process["exe"].endswith("python3.11")
        dump = STATE / "source.dump"
        dump.write_bytes(docker("exec", DBS[0], "pg_dump", "-Fc", "--no-owner", "--no-acl", "-U", "pp_stage3_owner", "-d", "proppulse_test_stage3", binary=True).stdout)
        assert dump.read_bytes().startswith(b"PGDMP")
        assert sql(DBS[1], "proppulse_test_stage3_restore", "SELECT count(*) FROM pg_tables WHERE schemaname='public';") == "0"
        docker("exec", "-i", DBS[1], "pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges",
            "-U", "pp_stage3_owner", "-d", "proppulse_test_stage3_restore", data=dump.read_bytes(), binary=True)
        sql(DBS[1], "proppulse_test_stage3_restore", grants, "pp_stage3_owner")
        after = worker(owners[1], "fingerprint", evidence="restored-after-backup")
        assert before == after
        restored_role = worker(applications[1], "verify-app-role")
        restored_auth = worker(configs[1], "restored-auth", auth_mode=True)
        assert worker(owners[0], "fingerprint", evidence="source-final") == before
        assert worker(owners[1], "fingerprint", evidence="restored-final") == before
        report = {"backend_image": backend, "postgres_image": postgres,
            "postgres_version": sql(DBS[0], "postgres", "SHOW server_version;"), "postgres_uid": 70, "gosu_absent": True,
            "api_uid": process["uid"], "default_command_http": api_report, "dns": True,
            "revision": before["revision"], "tables": len(before["tables"]), "rows": sum(t["rows"] for t in before["tables"].values()),
            "row_hashes_match": True, "source_auth": source_auth, "restored_auth": restored_auth,
            "least_privilege": role, "restored_least_privilege": restored_role,
            "backup_bytes": dump.stat().st_size, "backup_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(), "atomic_restore": True}
        (STATE / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
    finally:
        # Only resources successfully created by this run, with exact labels.
        for name in reversed(created):
            inspection = docker("inspect", name, check=False)
            if inspection.returncode:
                continue
            state = json.loads(inspection.stdout)[0]
            if (state["Config"].get("Labels", {}).get("proppulse.task") != LABEL
                    or state["Config"]["Labels"].get("proppulse.run") != run_id):
                raise RuntimeError("Refusing cleanup of an unowned container")
            docker("rm", "-f", name)
        if network_created:
            state = json.loads(docker("network", "inspect", NETWORK).stdout)[0]
            if state.get("Labels", {}).get("proppulse.task") != LABEL or state["Labels"].get("proppulse.run") != run_id:
                raise RuntimeError("Refusing cleanup of an unowned network")
            docker("network", "rm", NETWORK)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-image", default="proppulse-backend:hardened")
    parser.add_argument("--postgres-image", default="proppulse-postgres:nonroot")
    parser.add_argument("--evidence-dir", type=Path, default=STATE)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    if not evidence.is_relative_to(STATE.parent.resolve()):
        raise RuntimeError("Evidence must remain in this task's private PostgreSQL directory")
    STATE = evidence
    run(args.backend_image, args.postgres_image)
