"""Explicit local HTTPS/gateway probes; run after browser flows (consumes quotas).

Only loopback3443 and labelled disposable containers are addressed. No provider
requests, credentials or development database access. Trust this run's generated
certificate, with normal certificate/hostname verification and SNI.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import argparse
import http.client
import json
import socket
import ssl
import time

from production_stack_control import STATE, docker, owned


class LocalHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(("127.0.0.1", 3443), timeout=self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def request(path, method="GET", body=None, headers=None, host="api.proppulse.test"):
    context = ssl.create_default_context(cafile=str(STATE / "test-cert.pem"))
    connection = LocalHTTPS(host, 3443, timeout=20, context=context)
    try:
        connection.request(method, path, body=body, headers={"Host": host + ":3443", **(headers or {})})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        return result
    finally:
        connection.close()


def restart_gateway():
    owned("container", "pp-stage3-gateway")
    docker("restart", "pp-stage3-gateway")
    for _ in range(30):
        try:
            if request("/health")[0] == 200:
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.2)
    raise RuntimeError("Disposable HTTPS gateway did not become ready")


def timeout_probe():
    restart_gateway()
    connection = LocalHTTPS("api.proppulse.test", 3443, timeout=22,
        context=ssl.create_default_context(cafile=str(STATE / "test-cert.pem")))
    try:
        connection.connect()
        connection.sock.sendall(b"POST /auth/login HTTP/1.1\r\nHost: api.proppulse.test:3443\r\n"
            b"Content-Type: application/json\r\nContent-Length: 100\r\nConnection: close\r\n\r\n{")
        started = time.monotonic()
        response = connection.sock.recv(4096)
        elapsed = time.monotonic() - started
        # Nginx can close an incomplete request without sending a response.
        status = int(response.split(b" ", 2)[1]) if response else "connection closed"
        assert status in (408, "connection closed") and 13 < elapsed < 20, (status, elapsed)
        result = {"slow_body_result": status, "seconds": round(elapsed, 2)}
        (STATE / "gateway-timeout.json").write_text(json.dumps(result), encoding="utf-8")
        print(json.dumps(result))
    finally:
        connection.close()


def run(gateway_only=False):
    for name in ("pp-stage3-gateway", "pp-stage3-api-a", "pp-stage3-api-b", "pp-stage3-db"):
        state = owned("container", name)
        assert state["State"]["Running"]
        if name != "pp-stage3-gateway":
            assert not any(state["HostConfig"]["PortBindings"].values())
        if "api-" in name:
            assert state["Config"]["User"] in {"appuser", "10001:10001"}
            assert state["HostConfig"]["ReadonlyRootfs"]
            assert state["HostConfig"]["CapDrop"] == ["ALL"]
            assert set(state["NetworkSettings"]["Networks"]) == {"pp-stage3-private"}
    assert owned("network", "pp-stage3-private")["Internal"]
    # Fresh shared gateway zones make exact credential quota assertions repeatable.
    restart_gateway()
    for path in ("/health", "/ready"):
        status, headers, body = request(path)
        assert status == 200 and set(json.loads(body)) == {"status"}
    assert request("/login", host="app.proppulse.test")[0] == 200
    large = request("/auth/login", "POST", headers={"Content-Length": str(1024 * 1024 + 1)})
    assert large[0] == 413
    auth = []
    for number in range(12):
        auth.append(request("/auth/login", "POST", "{}", {
            "Content-Type": "application/json", "X-Forwarded-For": f"198.51.100.{number + 1}",
            "Cookie": "Stage3LogSentinel=not-a-session", "Authorization": "Stage3LogSentinel",
            "X-CSRF-Token": "Stage3LogSentinel"}))
    assert sum(status == 429 for status, _, _ in auth) >= 2
    assert all(headers.get("Retry-After") == "60" for status, headers, _ in auth if status == 429)
    # API quota is shared across both gateway workers and both upstream replicas.
    with ThreadPoolExecutor(max_workers=40) as pool:
        api = list(pool.map(lambda _: request("/health"), range(150)))
    assert any(status == 429 for status, _, _ in api)
    assert all(status in {200, 429} for status, _, _ in api)
    # Direct internal probes cannot spoof the gateway's trusted socket address.
    # Distinct emails isolate the client budget from the account budget.
    internal = '''import http.client,json
out=[]
for i in range(21):
 c=http.client.HTTPConnection('127.0.0.1',8000,timeout=10)
 c.request('POST','/auth/login',json.dumps({'email':f'backstop-{i}@example.invalid','password':'Stage3LogSentinel'}),{'Content-Type':'application/json','X-Forwarded-For':f'198.51.100.{i+1}'})
 r=c.getresponse();out.append([r.status,r.getheader('Retry-After')]);r.read();c.close()
assert all(x[0] != 429 for x in out[:20]),out
assert out[20][0] == 429 and int(out[20][1]) > 0,out
print(json.dumps({'statuses':[x[0] for x in out],'retry_after':int(out[20][1])}))'''
    backstop = None if gateway_only else json.loads(docker("exec", "pp-stage3-api-a", "python", "-c", internal))
    for name in ("pp-stage3-gateway", "pp-stage3-api-a", "pp-stage3-api-b"):
        assert "Stage3LogSentinel" not in docker("logs", name)
    result = {"https_hostname_verified": True, "private_runtime": True,
        "body_limit": large[0], "gateway_auth": dict(Counter(x[0] for x in auth)),
        "gateway_api": dict(Counter(x[0] for x in api)), "gateway_retry_after": 60,
        "backstop": backstop, "forwarding_spoof_bypass": False, "sentinel_logging": False}
    name = "gateway-patched-results.json" if gateway_only else "gateway-results.json"
    (STATE / name).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-only", action="store_true")
    parser.add_argument("--timeout-only", action="store_true")
    args = parser.parse_args()
    timeout_probe() if args.timeout_only else run(args.gateway_only)
