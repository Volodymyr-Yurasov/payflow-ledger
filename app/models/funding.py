from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Funding(Base):
    __tablename__ = "fundings"

    # Each account.funded event is its own top-up, so the event id is the identity.
    event_id: Mapped[str] = mapped_column(Text, ForeignKey("webhook_events.id"), primary_key=True)
    account_id: Mapped[str] = mapped_column(Text, ForeignKey("accounts.id"), index=True)
    amount: Mapped[Decimal]
    created_at: Mapped[datetime]
