"""Server configuration from ``MINDMESH_*`` environment variables, with production safety checks."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlsplit

DEFAULT_DEV_KEY = "mm_dev_local_key_change_me"
DEFAULT_APPS = "mindmesh.demo.refund,mindmesh.demo.research"
DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173"
MIN_SECRET_LEN = 32


class ConfigError(ValueError):
    """The configuration is unsafe or invalid for the selected environment."""


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Settings:
    env: str = "development"  # development | production
    database_url: str = "sqlite:///mindmesh.db"
    database_url_set: bool = False
    project: str = "default"
    api_key: str | None = None
    secret_key: str | None = None
    cors_origins: list[str] = field(default_factory=lambda: _list(DEFAULT_CORS))
    apps: str = DEFAULT_APPS
    model: str | None = None
    studio_dir: str | None = None
    auto_migrate: bool = True
    max_body_bytes: int = 1_048_576
    stream_token_ttl_s: int = 60
    docs: bool = True
    # Public read-only demo: a ``read`` key for a separate project, safe to embed in a public Studio build.
    public_key: str | None = None
    public_project: str = "demo"
    seed_public: bool = False
    # Requests per minute per client IP (0 disables); writes also count against the stricter write limit.
    rate_limit: int = 300
    rate_limit_writes: int = 60
    client_ip_header: str | None = None  # set by the edge proxy, e.g. true-client-ip

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        e = os.environ if environ is None else environ
        env = e.get("MINDMESH_ENV", "development").strip().lower()
        prod = env == "production"
        return cls(
            env=env,
            database_url=e.get("MINDMESH_DATABASE_URL") or "sqlite:///mindmesh.db",
            database_url_set=bool(e.get("MINDMESH_DATABASE_URL")),
            project=e.get("MINDMESH_PROJECT", "default"),
            api_key=e.get("MINDMESH_API_KEY") or None,
            secret_key=e.get("MINDMESH_SECRET_KEY") or None,
            cors_origins=_list(e.get("MINDMESH_CORS_ORIGINS", "" if prod else DEFAULT_CORS)),
            apps=e.get("MINDMESH_APPS", DEFAULT_APPS),
            model=e.get("MINDMESH_MODEL") or None,
            studio_dir=e.get("MINDMESH_STUDIO_DIR") or None,
            auto_migrate=_bool(e.get("MINDMESH_AUTO_MIGRATE"), True),
            max_body_bytes=int(e.get("MINDMESH_MAX_BODY_BYTES", "1048576")),
            stream_token_ttl_s=int(e.get("MINDMESH_STREAM_TOKEN_TTL", "60")),
            docs=_bool(e.get("MINDMESH_DOCS"), not prod),
            public_key=e.get("MINDMESH_PUBLIC_KEY") or None,
            public_project=e.get("MINDMESH_PUBLIC_PROJECT", "demo"),
            seed_public=_bool(e.get("MINDMESH_SEED_PUBLIC"), False),
            rate_limit=int(e.get("MINDMESH_RATE_LIMIT", "300")),
            rate_limit_writes=int(e.get("MINDMESH_RATE_LIMIT_WRITES", "60")),
            client_ip_header=e.get("MINDMESH_CLIENT_IP_HEADER") or None,
        )

    def validate(self) -> list[str]:
        """Raise :class:`ConfigError` on unsafe production settings; return warnings for development."""
        if self.env not in ("development", "production"):
            raise ConfigError(f"MINDMESH_ENV must be 'development' or 'production', not {self.env!r}")
        if self.max_body_bytes < 1024:
            raise ConfigError("MINDMESH_MAX_BODY_BYTES must be at least 1024")
        if not 5 <= self.stream_token_ttl_s <= 3600:
            raise ConfigError("MINDMESH_STREAM_TOKEN_TTL must be between 5 and 3600 seconds")
        if self.rate_limit < 0 or self.rate_limit_writes < 0:
            raise ConfigError("MINDMESH_RATE_LIMIT and MINDMESH_RATE_LIMIT_WRITES must be >= 0 (0 disables)")
        if self.public_key is not None:
            if self.public_key == self.api_key:
                raise ConfigError("MINDMESH_PUBLIC_KEY must differ from MINDMESH_API_KEY")
            if self.public_project == self.project:
                raise ConfigError("MINDMESH_PUBLIC_PROJECT must differ from MINDMESH_PROJECT (the demo is separate)")
            if len(self.public_key) < 16:
                raise ConfigError("MINDMESH_PUBLIC_KEY must be at least 16 characters")
        for origin in self.cors_origins:
            if origin != "*" and (urlsplit(origin).scheme not in ("http", "https") or not urlsplit(origin).netloc):
                raise ConfigError(f"invalid CORS origin {origin!r} (expected scheme://host[:port])")

        problems: list[str] = []
        if not self.api_key:
            problems.append("MINDMESH_API_KEY is not set")
        elif self.api_key == DEFAULT_DEV_KEY:
            problems.append("MINDMESH_API_KEY is the public development key")
        elif len(self.api_key) < MIN_SECRET_LEN:
            problems.append(f"MINDMESH_API_KEY must be at least {MIN_SECRET_LEN} characters")
        if not self.secret_key:
            problems.append("MINDMESH_SECRET_KEY is not set (signs stream tokens)")
        elif len(self.secret_key) < MIN_SECRET_LEN:
            problems.append(f"MINDMESH_SECRET_KEY must be at least {MIN_SECRET_LEN} characters")
        if "*" in self.cors_origins:
            problems.append("MINDMESH_CORS_ORIGINS must list explicit origins, not '*'")
        if not self.database_url_set or not self.database_url.startswith(("postgresql", "postgres://")):
            problems.append("MINDMESH_DATABASE_URL must point to PostgreSQL")

        if self.is_production and problems:
            raise ConfigError("unsafe production configuration:\n  - " + "\n  - ".join(problems))
        return problems

    def resolved_api_key(self) -> str:
        return self.api_key or ("" if self.is_production else DEFAULT_DEV_KEY)

    def resolved_secret_key(self) -> str:
        # Development: a per-process secret, so stream tokens simply expire on restart.
        if not self.secret_key:
            self.secret_key = secrets.token_urlsafe(32)
        return self.secret_key
