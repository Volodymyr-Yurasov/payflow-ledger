from datetime import datetime

from sqlalchemy import CHAR, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Account(Base):
    """One row per PayFlow account.

    The row is created by the first event that mentions the account (in any order),
    which pins its currency and gives us a row to lock. The account only becomes
    visible through the API once `opened_at` is set by an `account.funded` event.
    """

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    currency: Mapped[str] = mapped_column(CHAR(3))
    opened_at: Mapped[datetime | None]
