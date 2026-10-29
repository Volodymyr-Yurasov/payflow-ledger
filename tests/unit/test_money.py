from decimal import Decimal

import pytest

from app.core.money import format_amount, parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("125.50", Decimal("125.50")),
        ("0.00", Decimal("0.00")),
        ("10", Decimal("10.00")),
        ("10.5", Decimal("10.50")),
        ("9999999999999999.99", Decimal("9999999999999999.99")),
    ],
)
def test_parse_valid_amounts(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        125.5,  # JSON number: may already have been through float
        125,
        None,
        "",
        "-1.00",
        "+1.00",
        "1.234",  # no silent rounding of money
        "1e3",
        "NaN",
        "Infinity",
        " 1.00",
        "1,00",
        "12345678901234567.00",  # doesn't fit NUMERIC(18,2)
    ],
)
def test_parse_rejects_invalid_amounts(raw):
    with pytest.raises(ValueError):
        parse_amount(raw)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("585"), "585.00"),
        (Decimal("15.5"), "15.50"),
        (Decimal("0"), "0.00"),
        (None, "0.00"),
        (Decimal("-10.25"), "-10.25"),
    ],
)
def test_format_amount_has_two_decimals(amount, expected):
    assert format_amount(amount) == expected
