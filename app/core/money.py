"""Money parsing and formatting. Amounts are Decimal end to end, never float."""

from __future__ import annotations

import re
from decimal import Decimal

CENT = Decimal("0.01")

# PayFlow sends amounts as decimal strings with two decimal places. We also accept
# fewer decimals ("10", "10.5"), but never more (no silent rounding of money), no sign,
# no exponent. 16 integer digits is what NUMERIC(18,2) can hold.
_AMOUNT_RE = re.compile(r"\d{1,16}(\.\d{1,2})?")


def parse_amount(value: object) -> Decimal:
    if not isinstance(value, str):
        # A JSON number would already have gone through float in most parsers.
        raise ValueError("amount must be a decimal string, e.g. \"125.50\"")
    if not _AMOUNT_RE.fullmatch(value):
        raise ValueError(f"invalid amount {value!r}: expected a non-negative decimal "
                         "with at most 2 decimal places")
    return Decimal(value).quantize(CENT)


def format_amount(amount: Decimal | None) -> str:
    return str((amount or Decimal(0)).quantize(CENT))
