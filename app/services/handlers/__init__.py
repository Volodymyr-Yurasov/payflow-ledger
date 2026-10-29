"""Registry of event types we understand. Adding a type = one module + one line here."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.events import (
    AccountFundedData,
    AuthorizationCapturedData,
    AuthorizationCreatedData,
    AuthorizationReversedData,
    Event,
    RefundCreatedData,
)
from app.services.handlers import (
    account_funded,
    authorization_captured,
    authorization_created,
    authorization_reversed,
    refund_created,
)
from app.services.handlers.common import Rejected


@dataclass(frozen=True)
class Handler:
    data_model: type
    # Returns the resulting EventStatus (APPLIED or NOOP), or raises Rejected.
    apply: Callable[[Session, Event[Any]], str]


HANDLERS: dict[str, Handler] = {
    "account.funded": Handler(AccountFundedData, account_funded.apply),
    "authorization.created": Handler(AuthorizationCreatedData, authorization_created.apply),
    "authorization.captured": Handler(AuthorizationCapturedData, authorization_captured.apply),
    "authorization.reversed": Handler(AuthorizationReversedData, authorization_reversed.apply),
    "refund.created": Handler(RefundCreatedData, refund_created.apply),
}

__all__ = ["HANDLERS", "Handler", "Rejected"]
