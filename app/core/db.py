"""Transaction helper: every unit of work runs in one transaction with tight timeouts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)

T = TypeVar("T")

# serialization_failure, deadlock_detected: safe to retry the whole transaction.
TRANSIENT_SQLSTATES = frozenset({"40001", "40P01"})


def sqlstate(exc: BaseException) -> str | None:
    return getattr(getattr(exc, "orig", None), "sqlstate", None)


class TransactionRunner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        statement_timeout_ms: int,
        lock_timeout_ms: int,
        attempts: int = 3,
    ) -> None:
        self._session_factory = session_factory
        self._statement_timeout = str(statement_timeout_ms)
        self._lock_timeout = str(lock_timeout_ms)
        self._attempts = attempts

    def run(self, work: Callable[[Session], T]) -> T:
        """Run `work` in a fresh transaction; commit on return, roll back on exception.

        Deadlocks and serialization failures are retried; every other error propagates.
        """
        attempt = 1
        while True:
            try:
                with self._session_factory() as session, session.begin():
                    # SET LOCAL equivalents: scoped to this transaction only.
                    session.execute(
                        text(
                            "SELECT set_config('statement_timeout', :st, true),"
                            " set_config('lock_timeout', :lt, true)"
                        ),
                        {"st": self._statement_timeout, "lt": self._lock_timeout},
                    )
                    return work(session)
            except OperationalError as exc:
                if sqlstate(exc) not in TRANSIENT_SQLSTATES or attempt >= self._attempts:
                    raise
                log.warning(
                    "transient transaction failure, retrying",
                    extra={"attempt": attempt, "sqlstate": sqlstate(exc)},
                )
                attempt += 1
