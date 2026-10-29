"""Authorization status, derived from which facts we hold, never from arrival order."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal


class AuthStatus:
    PENDING = "pending"
    CAPTURED = "captured"
    REVERSED = "reversed"


def derive_status(captured_amount: Decimal | None, reversed_at: datetime | None) -> str:
    # A capture beats a reversal: if PayFlow ever reports both, money really moved.
    if captured_amount is not None:
        return AuthStatus.CAPTURED
    if reversed_at is not None:
        return AuthStatus.REVERSED
    return AuthStatus.PENDING
