"""Host-only session cookies and session-bound double-submit CSRF proofs."""
import hashlib
import hmac
import re
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from app.config import settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def cookie_name(kind):
    return ("__Host-" if settings.production else "") + "proppulse_" + kind


def session_token(request: Request):
    return request.cookies.get(cookie_name("session"))


def _cookie_options():
    return dict(httponly=True, secure=settings.production, path="/",
                samesite=settings.AUTH_COOKIE_SAMESITE)


def set_session(response: Response, token: str):
    response.set_cookie(cookie_name("session"), token,
        max_age=settings.JWT_EXPIRE_MINUTES * 60, **_cookie_options())
    response.headers["Cache-Control"] = "no-store"


def clear_session(response: Response):
    for kind in ("session", "csrf"):
        response.delete_cookie(cookie_name(kind), **_cookie_options())
    response.headers["Cache-Control"] = "no-store"


def _proof(nonce, token):
    binding = hashlib.sha256((token or "").encode()).hexdigest()
    return hmac.new(settings.JWT_SECRET.encode(),
        ("proppulse-csrf-v1:" + nonce + ":" + binding).encode(), hashlib.sha256).hexdigest()


def issue_csrf(request: Request, response: Response):
    nonce = request.cookies.get(cookie_name("csrf"), "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce):
        nonce = secrets.token_urlsafe(32)
    response.set_cookie(cookie_name("csrf"), nonce,
        max_age=settings.JWT_EXPIRE_MINUTES * 60, **_cookie_options())
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": _proof(nonce, session_token(request))}


def _origin(request):
    origin = request.headers.get("origin")
    if origin is not None:
        return origin
    referer = request.headers.get("referer")
    if not referer:
        return None
    try:
        parsed = urlsplit(referer)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return None
        return parsed.scheme + "://" + parsed.netloc
    except ValueError:
        return None


def require_csrf(request: Request):
    nonce = request.cookies.get(cookie_name("csrf"), "")
    supplied = request.headers.get("x-csrf-token", "")
    if (_origin(request) not in settings.CORS_ORIGINS
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce)
            or not re.fullmatch(r"[0-9a-f]{64}", supplied)
            or not hmac.compare_digest(supplied, _proof(nonce, session_token(request)))):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def require_cookie_csrf(request: Request):
    if session_token(request) is not None and request.method not in SAFE_METHODS:
        require_csrf(request)
