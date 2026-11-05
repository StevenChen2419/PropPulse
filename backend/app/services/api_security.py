"""Bounded request parsing and single-process abuse backstop.

Use a trusted gateway for fleet-wide limits. Client identity is the ASGI client
address; forwarding headers are never interpreted here.
"""
import asyncio
from collections import deque
import hashlib
import json
import logging
import math
import time

from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class WindowLimiter:
    def __init__(self, clock=time.monotonic, max_keys=4096):
        self.clock, self.max_keys = clock, max_keys
        self.windows = {}
        self.next_cleanup = 0

    def check(self, rules):
        now = self.clock()
        if now >= self.next_cleanup:
            self.windows = {key: (end, hits) for key, (end, hits) in self.windows.items() if end > now}
            self.next_cleanup = now + 60
        # Validate all budgets before consuming any of them.
        pending = []
        for key, limit, seconds in rules:
            end, hits = self.windows.get(key, (now + seconds, deque()))
            if end <= now:
                end, hits = now + seconds, deque()
            while hits and hits[0] <= now - seconds:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, math.ceil(hits[0] + seconds - now))
            pending.append((key, seconds, hits))
        new = {key for key, _, _ in pending if key not in self.windows}
        if len(self.windows) + len(new) > self.max_keys:
            # Do not evict live account limits, which would let churn bypass them.
            return 60
        for key, seconds, hits in pending:
            hits.append(now)
            self.windows[key] = (now + seconds, hits)
        return 0


class APISecurityMiddleware:
    def __init__(self, app, settings, limiter=None):
        self.app, self.settings = app, settings
        self.limiter = limiter or WindowLimiter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        path, method = scope["path"], scope["method"]

        async def reject(status, detail, retry=None):
            extra = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
            if retry:
                extra["Retry-After"] = str(retry)
            await JSONResponse({"detail": detail}, status_code=status, headers=extra)(scope, receive, send)

        if len(scope.get("query_string", b"")) > 4096:
            return await reject(414, "Query string too long")
        length = headers.get(b"content-length")
        if length is not None:
            try:
                if not length.isdigit():
                    raise ValueError()
                if int(length) > self.settings.API_MAX_BODY_BYTES:
                    return await reject(413, "Request body too large")
            except ValueError:
                return await reject(400, "Invalid content length")
        # Apply client limits before reading/parsing bodies or hashing passwords.
        client = (scope.get("client") or ("unknown", 0))[0]
        client = hashlib.sha256(client.encode()).hexdigest()
        auth_action = path.rstrip("/") in {"/auth/login", "/auth/register"} and method == "POST"
        if method != "OPTIONS" and path not in {"/health", "/ready"}:
            if auth_action:
                registration = path.rstrip("/") == "/auth/register"
                rules = [(('register' if registration else 'login', client),
                          5 if registration else 20, 3600 if registration else 900)]
            else:
                expensive = path.startswith(("/props", "/rankings")) or path.endswith(("/research", "/fatigue", "/game-log"))
                rules = [(("research" if expensive else "api", client), 120 if expensive else 300, 60)]
            retry = self.limiter.check(rules)
            if retry:
                return await reject(429, "Too many requests. Try again later.", retry)

        body = bytearray()
        deadline = asyncio.get_running_loop().time() + 15
        while True:
            try:
                message = await asyncio.wait_for(receive(), max(0.001, deadline - asyncio.get_running_loop().time()))
            except asyncio.TimeoutError:
                return await reject(408, "Request body timed out")
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.settings.API_MAX_BODY_BYTES:
                return await reject(413, "Request body too large")
            if not message.get("more_body", False):
                break
        if body and method in {"POST", "PUT", "PATCH", "DELETE"}:
            content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
            # Current application mutation contracts are JSON; no upload route is
            # registered. Responses/downloads are not size/content-type limited.
            if content_type != b"application/json":
                return await reject(415, "Use application/json")
        if auth_action:
            try:
                data = json.loads(body)
                email = data.get("email") if isinstance(data, dict) else None
            except (ValueError, UnicodeError, RecursionError):
                email = None
            if isinstance(email, str) and len(email) <= 254:
                digest = hashlib.sha256(email.strip().casefold().encode()).hexdigest()
                registration = path.rstrip("/") == "/auth/register"
                retry = self.limiter.check([(("register-account" if registration else "login-account", digest),
                                             3 if registration else 10, 3600 if registration else 900)])
                if retry:
                    return await reject(429, "Too many requests. Try again later.", retry)

        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        started = False
        async def secured_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                items = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                items.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                              (b"referrer-policy", b"strict-origin-when-cross-origin")])
                message["headers"] = items
            await send(message)
        try:
            await self.app(scope, replay, secured_send)
        except Exception:
            # No raw exception, submitted body, headers, tokens or query strings.
            logger.error("Unhandled API exception")
            if started:
                raise
            await reject(500, "Internal server error")
