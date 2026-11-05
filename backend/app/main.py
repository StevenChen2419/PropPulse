from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app.config import settings
from app.services.readiness_service import check_readiness
from fastapi.responses import JSONResponse
from app.routers import props, players, users, interactions, rankings
from app.services.live_refresh_service import LiveRefresh
from fastapi.exceptions import RequestValidationError
from app.services.api_security import APISecurityMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI):
    errors = settings.configuration_errors()
    if errors:
        raise RuntimeError("Invalid application configuration: " + ", ".join(errors))
    if settings.production:
        result = check_readiness(engine, settings)
        if result["status"] != "ready":
            raise RuntimeError("Database prerequisites unavailable: " + result["reason"])
    refresh = LiveRefresh()
    if settings.LIVE_REFRESH_ENABLED:
        refresh.start()
    try:
        yield
    finally:
        refresh.stop()


app = FastAPI(title="PropPulse API", version="0.1.0", lifespan=lifespan, debug=False)


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    # Pydantic's input/ctx can contain submitted passwords or credential values.
    return JSONResponse({"detail": [{"loc": error["loc"], "msg": error["msg"],
                                      "type": error["type"]} for error in exc.errors()]}, status_code=422)

app.add_middleware(APISecurityMiddleware, settings=settings)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if not settings.configuration_errors() else [],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)

app.include_router(users.router,        prefix="/auth",        tags=["auth"])
app.include_router(users.user_router,   prefix="/users",       tags=["users"])
app.include_router(props.router,        prefix="/props",       tags=["props"])
app.include_router(players.router,      prefix="/players",     tags=["players"])
app.include_router(interactions.router, prefix="/interactions", tags=["interactions"])
app.include_router(rankings.router,     prefix="/rankings",    tags=["rankings"])

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    result = check_readiness(engine, settings)
    return JSONResponse(result, status_code=200 if result["status"] == "ready" else 503,
                        headers={"Cache-Control": "no-store"})
