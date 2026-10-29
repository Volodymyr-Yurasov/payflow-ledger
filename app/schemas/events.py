"""Per-type payload models for the event types we understand.

Unknown extra fields are ignored rather than rejected: PayFlow may add fields
to existing events, and that shouldn't break us.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StrictStr,
    StringConstraints,
)

from app.core.money import parse_amount

Id = Annotated[StrictStr, StringConstraints(min_length=1, max_length=255)]
Money = Annotated[Decimal, BeforeValidator(parse_amount)]
Currency = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z]{3}$")]


class _Data(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    account_id: Id
    amount: Money
    currency: Currency


class AccountFundedData(_Data):
    pass


class AuthorizationCreatedData(_Data):
    authorization_id: Id
    merchant: Annotated[StrictStr, StringConstraints(max_length=500)]


class AuthorizationCapturedData(_Data):
    authorization_id: Id


class AuthorizationReversedData(_Data):
    authorization_id: Id


class RefundCreatedData(_Data):
    refund_id: Id
    authorization_id: Id


class _Meta(BaseModel):
    created_at: AwareDatetime


D = TypeVar("D", bound=_Data)


@dataclass(frozen=True)
class Event(Generic[D]):
    id: str
    type: str
    created_at: datetime
    data: D


def parse_event(payload: dict[str, Any], data_model: type[D]) -> Event[D]:
    """Raises pydantic.ValidationError when the payload doesn't fit the type."""
    meta = _Meta.model_validate({"created_at": payload.get("created_at")})
    data = data_model.model_validate(payload.get("data"))
    return Event(id=payload["id"], type=payload["type"], created_at=meta.created_at, data=data)
