"""Exceptions that map to specific HTTP responses, and the Flask handlers for them.

Status codes matter here: PayFlow treats anything but 2xx as a failed delivery and
retries for 72h. So 4xx is only for requests a retry could never fix *and* that we
can't even store (bad signature, unparseable body); transient problems are 5xx.
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)


class EventInFlight(Exception):
    """Another request is processing the same event id right now (Redis lock held)."""

    def __init__(self, event_id: str) -> None:
        super().__init__(event_id)
        self.event_id = event_id


def error_response(status: int, message: str):
    response = jsonify({"error": message})
    response.status_code = status
    return response


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(EventInFlight)
    def _in_flight(exc: EventInFlight):
        response = error_response(409, "event is being processed, retry later")
        response.headers["Retry-After"] = "2"
        return response

    # Connection refused, statement/lock timeouts, deadlocks after retries, pool
    # exhaustion: all transient, so 503 and let PayFlow retry.
    @app.errorhandler(OperationalError)
    @app.errorhandler(PoolTimeoutError)
    def _db_unavailable(exc: Exception):
        log.error("database unavailable", exc_info=exc)
        return error_response(503, "database unavailable, retry later")

    @app.errorhandler(HTTPException)
    def _http(exc: HTTPException):
        return error_response(exc.code or 500, exc.description or exc.name)

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        log.exception("unhandled error")
        return error_response(500, "internal error")
