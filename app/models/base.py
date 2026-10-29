from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # Money is always NUMERIC(18,2) (never float); timestamps are always timezone-aware.
    type_annotation_map = {
        Decimal: Numeric(18, 2),
        datetime: DateTime(timezone=True),
    }
