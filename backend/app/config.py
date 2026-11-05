from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal
from urllib.parse import urlsplit
from sqlalchemy.engine import make_url

class Settings(BaseSettings):
    DATABASE_URL: str = Field(default="postgresql://proppulse:proppulse@localhost:5432/proppulse", repr=False)
    REDIS_URL: str = Field(default="redis://localhost:6379/0", repr=False)
    JWT_SECRET: str = Field(default="changeme", repr=False)
    JWT_ALGORITHM: Literal["HS256"] = "HS256"
    JWT_EXPIRE_MINUTES: int = Field(default=120, ge=1, le=43200)
    AUTH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    # This is an operator acknowledgement, not an implementation of edge limits.
    GATEWAY_RATE_LIMIT_ENABLED: bool = False
    API_MAX_BODY_BYTES: int = Field(default=1048576, ge=1024, le=10485760)
    ENVIRONMENT: Literal["development", "test", "staging", "production"] = "development"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @property
    def production(self):
        return self.ENVIRONMENT in {"production", "staging"}

    @property
    def cookie_secure(self):
        return self.production

    def configuration_errors(self):
        """Return field identifiers only; never interpolate configuration values."""
        errors = []
        if self.production:
            if self.JWT_EXPIRE_MINUTES > 1440:
                errors.append("jwt_expiry")
            if not self.GATEWAY_RATE_LIMIT_ENABLED:
                errors.append("gateway_rate_limit")
            secret = self.JWT_SECRET.strip()
            if (len(secret.encode()) < 32 or len(set(secret)) < 12
                    or any(word in secret.lower() for word in ("changeme", "placeholder", "replace", "example", "supersecret"))):
                errors.append("jwt_secret")
            if "DATABASE_URL" not in self.model_fields_set or not self.DATABASE_URL.strip():
                errors.append("database_url")
            try:
                database = make_url(self.DATABASE_URL)
                if (database.get_backend_name() != "postgresql" or not database.host
                        or not database.database or not database.username
                        or self.DATABASE_URL == type(self).model_fields["DATABASE_URL"].default):
                    errors.append("database_url")
            except Exception:
                errors.append("database_url")
            if "CORS_ORIGINS" not in self.model_fields_set or not self.CORS_ORIGINS:
                errors.append("cors_origins")
        if self.AUTH_COOKIE_SAMESITE == "none" and not self.cookie_secure:
            errors.append("auth_cookie_samesite")
        for origin in self.CORS_ORIGINS:
            try:
                value = urlsplit(origin)
                valid = (value.scheme in ({"https"} if self.production else {"http", "https"})
                         and value.hostname and not value.username and not value.password
                         and not value.path and not value.query and not value.fragment
                         and not any(char.isspace() or char in "*\\%" for char in origin)
                         and value.port != 0)
            except ValueError:
                valid = False
            if not valid:
                errors.append("cors_origins")
        return sorted(set(errors))
    balldontlie_api_key: str = Field(default="", repr=False)
    the_odds_api_key: str = Field(default="", repr=False)
    LIVE_REFRESH_ENABLED: bool = False
    ODDS_REFRESH_SECONDS: int = Field(default=900, ge=60)
    HISTORY_REFRESH_SECONDS: int = Field(default=21600, ge=300)
    ODDS_MIN_REMAINING_CREDITS: int = Field(default=50, ge=0)
    ODDS_EVENT_HORIZON_HOURS: int = Field(default=48, ge=1)
    ODDS_MAX_REQUESTS_PER_RUN: int = Field(default=100, ge=1)
    ODDS_MAX_CREDITS_PER_RUN: int = Field(default=500, ge=1)
    ODDS_EVENT_FETCH_LIMIT: int = Field(default=0, ge=0)

    class Config:
        env_file = ".env"
        # The shared example also documents the frontend's public build setting.
        extra = "ignore"

settings = Settings()
