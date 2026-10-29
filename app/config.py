"""Service configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


@dataclass(frozen=True)
class Config:
    database_url: str
    webhook_secret: str
    # Empty / None disables the Redis shield entirely (Postgres alone stays correct).
    redis_url: str | None = None

    max_body_bytes: int = 64 * 1024
    # Both must stay well under PayFlow's 10s delivery timeout.
    statement_timeout_ms: int = 5_000
    lock_timeout_ms: int = 3_000

    db_pool_size: int = 8
    db_max_overflow: int = 4

    redis_socket_timeout_s: float = 0.2
    # Longer than PayFlow's 72h retry window, so late retries still hit the cache.
    redis_done_ttl_s: int = 4 * 24 * 3600
    # Longer than statement_timeout, so a live request never loses its lock.
    redis_lock_ttl_ms: int = 15_000

    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            database_url=os.environ["DATABASE_URL"],
            webhook_secret=os.environ["PAYFLOW_WEBHOOK_SECRET"],
            redis_url=os.environ.get("REDIS_URL") or None,
            max_body_bytes=_int_env("MAX_BODY_BYTES", 64 * 1024),
            statement_timeout_ms=_int_env("DB_STATEMENT_TIMEOUT_MS", 5_000),
            lock_timeout_ms=_int_env("DB_LOCK_TIMEOUT_MS", 3_000),
            db_pool_size=_int_env("DB_POOL_SIZE", 8),
            db_max_overflow=_int_env("DB_MAX_OVERFLOW", 4),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )

    def with_overrides(self, **changes: object) -> Config:
        return replace(self, **changes)
