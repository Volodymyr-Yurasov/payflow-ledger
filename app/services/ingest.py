"""Webhook ingestion: dedupe, then apply, exactly once.

The idempotency guarantee is the INSERT ... ON CONFLICT DO NOTHING on webhook_events.id,
executed in the SAME transaction as the ledger changes:

* two concurrent deliveries of one event: the second INSERT blocks on the unique index
  until the first transaction ends; if it committed, the second sees the conflict and
  answers "duplicate"; if it rolled back (crash, error), the second proceeds and applies.
* "event recorded" and "money moved" commit together or not at all, so there is no
  window in which an event is marked seen but not applied (or the other way around).
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.db import TransactionRunner
from app.core.errors import EventInFlight
from app.models import EventStatus, WebhookEvent
from app.schemas.events import parse_event
from app.services.handlers import HANDLERS, Rejected
from app.services.shield import LockState, Shield

log = logging.getLogger(__name__)


class Outcome(enum.StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    DUPLICATE_MISMATCH = "duplicate_mismatch"
    IGNORED = "ignored"
    QUARANTINED = "quarantined"


_OUTCOME_BY_STATUS = {
    EventStatus.APPLIED: Outcome.APPLIED,
    EventStatus.NOOP: Outcome.DUPLICATE,
    EventStatus.IGNORED: Outcome.IGNORED,
    EventStatus.REJECTED: Outcome.QUARANTINED,
}


def payload_digest(payload: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON. Not the dedup key (that's the event id, per PayFlow's
    contract), but lets us notice the same id arriving with different content."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class IngestService:
    def __init__(self, tx: TransactionRunner, shield: Shield) -> None:
        self._tx = tx
        self._shield = shield

    def ingest(self, payload: dict[str, Any]) -> Outcome:
        """`payload` must already be signature-checked and have string `id` and `type`."""
        event_id = payload["id"]
        digest = payload_digest(payload)
        if self._shield.is_done(event_id, digest):
            return Outcome.DUPLICATE

        lock = self._shield.acquire(event_id)
        if lock.state is LockState.BUSY:
            raise EventInFlight(event_id)
        try:
            outcome = self._tx.run(
                lambda session: self._claim_and_apply(session, payload, digest)
            )
            # Only after commit: the cache must never get ahead of the database. A
            # mismatching payload isn't cached, so every such resend gets flagged.
            if outcome is not Outcome.DUPLICATE_MISMATCH:
                self._shield.mark_done(event_id, digest)
        finally:
            self._shield.release(event_id, lock)
        return outcome

    def _claim_and_apply(self, session: Session, payload: dict[str, Any], digest: str) -> Outcome:
        event_id = payload["id"]
        claimed = session.execute(
            pg_insert(WebhookEvent)
            .values(
                id=event_id,
                type=payload["type"],
                account_id=_account_id_of(payload),
                payload=payload,
                payload_sha256=digest,
                event_created_at=_parse_timestamp(payload.get("created_at")),
                status=EventStatus.RECEIVED,
            )
            .on_conflict_do_nothing(index_elements=[WebhookEvent.id])
            .returning(WebhookEvent.id)
        ).scalar_one_or_none()

        if claimed is None:
            stored_digest = session.scalar(
                select(WebhookEvent.payload_sha256).where(WebhookEvent.id == event_id)
            )
            if stored_digest != digest:
                log.warning(
                    "event id re-delivered with a different payload; keeping the first",
                    extra={"event_id": event_id},
                )
                return Outcome.DUPLICATE_MISMATCH
            return Outcome.DUPLICATE

        status, error = apply_event(session, payload)
        session.execute(
            update(WebhookEvent)
            .where(WebhookEvent.id == event_id)
            .values(status=status, error=error)
        )
        return _OUTCOME_BY_STATUS[status]


def apply_event(session: Session, payload: dict[str, Any]) -> tuple[str, str | None]:
    """Apply one stored event to the ledger. Returns (EventStatus, error reason).

    Shared by live ingestion and the replay command.
    """
    handler = HANDLERS.get(payload["type"])
    if handler is None:
        # New types can appear without warning. Answering 4xx would make PayFlow retry
        # for 72h; instead we keep the event so it can be replayed once supported.
        log.info(
            "ignoring unknown event type",
            extra={"event_id": payload["id"], "event_type": payload["type"]},
        )
        return EventStatus.IGNORED, None

    try:
        # Savepoint: if the handler fails halfway, its partial writes are undone while
        # the event row itself stays (as rejected).
        with session.begin_nested():
            event = parse_event(payload, handler.data_model)
            return handler.apply(session, event), None
    except ValidationError as exc:
        reason = "invalid payload: " + "; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in exc.errors()
        )
    except Rejected as exc:
        reason = str(exc)

    log.error(
        "event quarantined",
        extra={"event_id": payload["id"], "event_type": payload["type"], "reason": reason},
    )
    return EventStatus.REJECTED, reason


def _account_id_of(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("account_id"), str):
        return data["account_id"][:255]
    return None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None
