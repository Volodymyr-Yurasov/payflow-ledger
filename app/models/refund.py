from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Refund(Base):
    __tablename__ = "refunds"

    # Keyed by PayFlow's refund_id, so the same refund re-sent under a new event id
    # is still counted once.
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    # No FK: a refund may arrive before its authorization does.
    authorization_id: Mapped[str] = mapped_column(Text, index=True)
    account_id: Mapped[str] = mapped_column(Text, ForeignKey("accounts.id"), index=True)
    amount: Mapped[Decimal]
    event_id: Mapped[str] = mapped_column(Text, ForeignKey("webhook_events.id"))
    created_at: Mapped[datetime]
