"""Redis fast path in front of the Postgres idempotency check.

Postgres is the source of truth (see services/ingest.py); this layer only makes
duplicate floods cheap:

* "done" cache:     written only AFTER the Postgres commit, so it can never claim an
                    event that isn't durably applied. Hits are answered without a DB call.
                    The value is the payload's SHA-256: a hit requires the same content,
                    so a reused id with a different payload still reaches Postgres and
                    gets flagged there.
* in-flight lock:   SET NX PX. While one request processes an event id, concurrent copies
                    get 409 and PayFlow retries them later (by then they hit the cache),
                    instead of every copy holding a DB connection.

Every method fails open: if Redis is down or slow, it reports "not done"/"no lock" and the
request falls through to Postgres, which is still fully correct on its own.

Circuit breaker: a failing Redis call can be slow (e.g. a DNS lookup for a vanished host
takes seconds, which socket timeouts don't cover). After one failure the shield skips
Redis entirely for `cooldown_s`, so an outage costs one slow call per cooldown instead of
three per request.
"""

from __future__ import annotations

import enum
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import redis

log = logging.getLogger(__name__)

# Delete the lock only if it's still ours: if it expired and another request took it,
# deleting it would let a third request in alongside that one.
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class LockState(enum.Enum):
    ACQUIRED = "acquired"
    BUSY = "busy"  # another request holds it
    UNAVAILABLE = "unavailable"  # Redis disabled or down: proceed without a lock


@dataclass(frozen=True)
class Lock:
    state: LockState
    token: str | None = None


class Shield:
    def __init__(
        self,
        client: redis.Redis | None,
        *,
        done_ttl_s: int,
        lock_ttl_ms: int,
        cooldown_s: float = 5.0,
        prefix: str = "pf:evt:",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._done_ttl_s = done_ttl_s
        self._lock_ttl_ms = lock_ttl_ms
        self._cooldown_s = cooldown_s
        self._prefix = prefix
        self._clock = clock
        self._skip_until = 0.0
        self._release = client.register_script(_RELEASE_SCRIPT) if client else None

    def _done_key(self, event_id: str) -> str:
        return f"{self._prefix}{event_id}:done"

    def _lock_key(self, event_id: str) -> str:
        return f"{self._prefix}{event_id}:lock"

    def _available(self) -> bool:
        return self._client is not None and self._clock() >= self._skip_until

    def is_done(self, event_id: str, digest: str) -> bool:
        if not self._available():
            return False
        try:
            return self._client.get(self._done_key(event_id)) == digest.encode()
        except redis.RedisError as exc:
            self._degraded("is_done", exc)
            return False

    def acquire(self, event_id: str) -> Lock:
        if not self._available():
            return Lock(LockState.UNAVAILABLE)
        token = uuid.uuid4().hex
        try:
            acquired = self._client.set(
                self._lock_key(event_id), token, nx=True, px=self._lock_ttl_ms
            )
        except redis.RedisError as exc:
            self._degraded("acquire", exc)
            return Lock(LockState.UNAVAILABLE)
        return Lock(LockState.ACQUIRED, token) if acquired else Lock(LockState.BUSY)

    def release(self, event_id: str, lock: Lock) -> None:
        if lock.state is not LockState.ACQUIRED or not self._available():
            # (If Redis just went down, the lock simply expires after lock_ttl_ms.)
            return
        try:
            self._release(keys=[self._lock_key(event_id)], args=[lock.token])
        except redis.RedisError as exc:
            # Harmless: the lock expires on its own after lock_ttl_ms.
            self._degraded("release", exc)

    def mark_done(self, event_id: str, digest: str) -> None:
        if not self._available():
            return
        try:
            self._client.set(self._done_key(event_id), digest, ex=self._done_ttl_s)
        except redis.RedisError as exc:
            # Harmless: the next duplicate is caught by Postgres instead.
            self._degraded("mark_done", exc)

    def status(self) -> str:
        if self._client is None:
            return "disabled"
        if not self._available():
            return "unavailable"
        try:
            self._client.ping()
            return "ok"
        except redis.RedisError as exc:
            self._degraded("ping", exc)
            return "unavailable"

    def _degraded(self, operation: str, exc: Exception) -> None:
        self._skip_until = self._clock() + self._cooldown_s
        log.warning(
            "redis unavailable, falling back to postgres",
            extra={"operation": operation, "error": repr(exc), "skip_s": self._cooldown_s},
        )
