import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.db import TransactionRunner


class _PgError(Exception):
    def __init__(self, sqlstate):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _runner(app, attempts=3):
    return TransactionRunner(
        app.extensions["payflow"].session_factory,
        statement_timeout_ms=1000,
        lock_timeout_ms=500,
        attempts=attempts,
    )


def test_deadlock_is_retried_then_succeeds(app):
    calls = []

    def work(session):
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("UPDATE ...", {}, _PgError("40P01"))
        return session.scalar(text("SELECT current_setting('statement_timeout')"))

    assert _runner(app).run(work) == "1s"  # timeouts are applied to every transaction
    assert len(calls) == 2


def test_transient_errors_give_up_after_max_attempts(app):
    def always_conflicts(session):
        raise OperationalError("UPDATE ...", {}, _PgError("40001"))

    with pytest.raises(OperationalError):
        _runner(app, attempts=2).run(always_conflicts)


def test_other_database_errors_are_not_retried(app):
    calls = []

    def lock_timeout(session):
        calls.append(1)
        raise OperationalError("SELECT ...", {}, _PgError("55P03"))

    with pytest.raises(OperationalError):
        _runner(app).run(lock_timeout)
    assert len(calls) == 1
