"""Verify official PostgreSQL's direct-UID startup never invokes gosu.

This opt-in probe owns only pp-image-gosu-probe. It has no network, host ports,
database mounts or application credentials. Evidence is private and ignored.
The executable tripwire is a test-only bind mask, never a production image fix.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "backend/data/odds_runs/container-image-remediation/pg/gosu-proof"
NAME = "pp-image-gosu-probe"
LABEL = "container-image-remediation"
IMAGE = "postgres:15-alpine@sha256:a8e042598834300dfaa17a54f695b87b7f25d3490433bbbe2ef3bffbb9747f24"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    if not evidence.is_relative_to(EVIDENCE.parent.resolve()):
        raise RuntimeError("Probe evidence must remain in the task's private PostgreSQL directory")
    if evidence.exists() and any(evidence.iterdir()):
        raise RuntimeError("Private probe evidence exists; refusing to overwrite it")
    evidence.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(40)
    endpoint = "npipe:////./pipe/docker_engine" if os.name == "nt" else "unix:///var/run/docker.sock"

    def docker(*parts, check=True):
        result = subprocess.run(["docker", "--host", endpoint, *map(str, parts)],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if check and result.returncode:
            (evidence / "gosu-probe-error.log").write_text(result.stderr.replace(password, "<redacted>"), encoding="utf-8")
            raise RuntimeError("PostgreSQL probe command failed; inspect private evidence")
        return result

    if docker("container", "inspect", NAME, check=False).returncode == 0:
        raise RuntimeError("Probe name already exists; refusing to adopt or replace a container")
    environment = evidence / "gosu-probe.env"
    environment.write_text("POSTGRES_USER=probe_admin\nPOSTGRES_DB=postgres\nPOSTGRES_PASSWORD=" + password + "\n", encoding="utf-8")
    tripwire = evidence / "gosu-tripwire.sh"
    tripwire.write_text("#!/bin/sh\nprintf 'invoked\\n' >> /tmp/gosu-tripwire-called\nexit 97\n", encoding="utf-8")
    created = False
    try:
        docker("run", "-d", "--pull", "never", "--name", NAME, "--label", "proppulse.task=" + LABEL,
            "--network", "none", "--user", "70:70", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "512m", "--cpus", "1", "--pids-limit", "128",
            "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=256m,uid=70,gid=70,mode=0700",
            "--tmpfs", "/var/run/postgresql:rw,noexec,nosuid,size=16m,uid=70,gid=70,mode=0775",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m,mode=1777", "--env-file", environment,
            "--mount", "type=bind,source=" + str(tripwire) + ",target=/usr/local/bin/gosu,readonly",
            args.image, "-c", "log_statement=none", "-c", "log_min_error_statement=panic")
        created = True
        for _ in range(45):
            ready = docker("exec", NAME, "pg_isready", "-U", "probe_admin", "-d", "postgres", check=False)
            final_process = docker("exec", NAME, "sh", "-c", 'test "$(readlink /proc/1/exe)" = /usr/local/bin/postgres', check=False)
            if ready.returncode == 0 and final_process.returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError("Direct-UID PostgreSQL did not become ready with the fail-closed gosu tripwire")
        state = json.loads(docker("inspect", NAME).stdout)[0]
        process = docker("exec", NAME, "sh", "-c",
            "test ! -e /tmp/gosu-tripwire-called && readlink /proc/1/exe && grep -E '^(Name|Uid|Gid|CapEff|NoNewPrivs):' /proc/1/status").stdout
        assert state["Config"]["User"] == "70:70"
        assert state["HostConfig"]["ReadonlyRootfs"] and state["HostConfig"]["CapDrop"] == ["ALL"]
        assert state["HostConfig"]["NetworkMode"] == "none" and not state["HostConfig"]["PortBindings"]
        assert "/postgres" in process and "CapEff:\t0000000000000000" in process and "NoNewPrivs:\t1" in process
        assert "Uid:\t70\t70\t70\t70" in process and "Gid:\t70\t70\t70\t70" in process
        result = {
            "image": args.image, "image_id": state["Image"], "gosu_tripwire_invocations": 0,
            "fresh_init_and_ready": True, "uid": 70, "gid": 70, "capabilities": "none", "no_new_privileges": True,
            "readonly_root": True, "network": "none", "host_ports": [], "pid1_process": process.strip(),
            "mitigation_only": True, "bundled_helper_findings_not_removed": True,
        }
        (evidence / "gosu-nonexecution-proof.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print("Fresh init/readiness succeeded with a fail-closed gosu tripwire; PID1 PostgreSQL UID70/capabilities0 verified.")
    finally:
        if created:
            state = json.loads(docker("inspect", NAME).stdout)[0]
            if state["Name"] != "/" + NAME or state["Config"].get("Labels", {}).get("proppulse.task") != LABEL:
                raise RuntimeError("Refusing cleanup of an unowned probe container")
            docker("rm", "-f", NAME)


if __name__ == "__main__":
    main()
