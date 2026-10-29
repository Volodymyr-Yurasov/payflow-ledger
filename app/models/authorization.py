from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Authorization(Base):
    """One row per authorization_id, assembled from facts in whatever order they arrive.

    Each lifecycle event only fills in its own columns; `status` is derived from which
    facts are present (see services/handlers/status.py), never from arrival order.
    """

    __tablename__ = "authorizations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(Text, ForeignKey("accounts.id"), index=True)
    currency: Mapped[str] = mapped_column(CHAR(3))
    status: Mapped[str] = mapped_column(Text)

    # authorization.created
    merchant: Mapped[str | None] = mapped_column(Text)
    authorized_amount: Mapped[Decimal | None]
    created_at: Mapped[datetime | None]

    # authorization.captured
    captured_amount: Mapped[Decimal | None]
    captured_at: Mapped[datetime | None]

    # authorization.reversed
    reversed_amount: Mapped[Decimal | None]
    reversed_at: Mapped[datetime | None]

    # Earliest PayFlow timestamp of any event for this authorization; used for ordering
    # until authorization.created (and with it the real created_at) arrives.
    first_seen_at: Mapped[datetime]
