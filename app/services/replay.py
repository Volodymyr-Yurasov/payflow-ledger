"""Re-apply stored events, e.g. quarantined ones after a fix, or ignored ones after
support for their type was added. Uses the same handlers and locks as live ingestion."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select

from app.core.db import TransactionRunner
from app.models import WebhookEvent
from app.services.ingest import apply_event


@dataclass(frozen=True)
class ReplayResult:
    event_id: str
    old_status: str
    new_status: str
    error: str | None


def replay_events(
    tx: TransactionRunner,
    *,
    statuses: Iterable[str],
    event_type: str | None = None,
    event_id: str | None = None,
) -> list[ReplayResult]:
    statuses = tuple(statuses)
    query = select(WebhookEvent.id).where(WebhookEvent.status.in_(statuses))
    if event_type:
        query = query.where(WebhookEvent.type == event_type)
    if event_id:
        query = query.where(WebhookEvent.id == event_id)
    query = query.order_by(WebhookEvent.event_created_at, WebhookEvent.id)
    ids = tx.run(lambda session: list(session.scalars(query)))

    results = []
    for current_id in ids:
        result = tx.run(lambda session, eid=current_id: _replay_one(session, eid, statuses))
        if result is not None:
            results.append(result)
    return results


def _replay_one(session, event_id: str, statuses: tuple[str, ...]) -> ReplayResult | None:
    row = session.get(WebhookEvent, event_id, with_for_update=True)
    if row is None or row.status not in statuses:  # changed since we listed it
        return None
    old_status = row.status
    row.status, row.error = apply_event(session, row.payload)
    return ReplayResult(event_id, old_status, row.status, row.error)
