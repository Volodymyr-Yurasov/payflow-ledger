import enum
from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EventStatus(enum.StrEnum):
    """Stored as plain TEXT: StrEnum members are str, so they compare and bind as-is."""

    RECEIVED = "received"  # only ever visible inside the claiming transaction
    APPLIED = "applied"
    NOOP = "noop"  # semantic duplicate (same fact under a new event id): stored, changed nothing
    IGNORED = "ignored"  # unknown event type: stored for replay once we support it
    REJECTED = "rejected"  # quarantined: invalid data or contradicts known facts


class WebhookEvent(Base):
    """Every signed event we accepted, whatever happened to it.

    The primary key on `id` is the idempotency guarantee: the row is inserted in the
    same transaction that applies the event, so "seen" and "applied" can't diverge.
    """

    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text)
    account_id: Mapped[str | None] = mapped_column(Text, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(CHAR(64))
    event_created_at: Mapped[datetime | None]
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    status: Mapped[str] = mapped_column(Text, index=True)
    error: Mapped[str | None] = mapped_column(Text)
