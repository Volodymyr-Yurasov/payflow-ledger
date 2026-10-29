from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.services.handlers.status import AuthStatus, derive_status

NOW = datetime(2026, 10, 19, tzinfo=UTC)


@pytest.mark.parametrize(
    ("captured_amount", "reversed_at", "expected"),
    [
        (None, None, AuthStatus.PENDING),
        (Decimal("10.00"), None, AuthStatus.CAPTURED),
        (Decimal("0.00"), None, AuthStatus.CAPTURED),
        (None, NOW, AuthStatus.REVERSED),
        # Contradiction from PayFlow: capture wins because money actually moved.
        (Decimal("10.00"), NOW, AuthStatus.CAPTURED),
    ],
)
def test_derive_status(captured_amount, reversed_at, expected):
    assert derive_status(captured_amount, reversed_at) == expected
