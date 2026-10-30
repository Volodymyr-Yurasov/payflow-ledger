from sqlalchemy.orm import Session

from app.models import EventStatus
from app.schemas.events import AuthorizationCreatedData, Event
from app.services.handlers.common import (
    Rejected,
    load_authorization,
    lock_account,
    refresh_status,
)


def apply(session: Session, event: Event[AuthorizationCreatedData]) -> EventStatus:
    data = event.data
    account = lock_account(session, data.account_id, data.currency)
    auth = load_authorization(session, account, data.authorization_id, event.created_at)

    if auth.authorized_amount is not None:
        if auth.authorized_amount == data.amount and auth.merchant == data.merchant:
            return EventStatus.NOOP
        raise Rejected(
            f"authorization {auth.id} already created with amount {auth.authorized_amount}"
            f" at {auth.merchant!r}; got {data.amount} at {data.merchant!r}"
        )

    # Only fills in its own facts. If the capture/reversal arrived first, the status
    # it set stays as is.
    auth.authorized_amount = data.amount
    auth.merchant = data.merchant
    auth.created_at = event.created_at
    refresh_status(auth)
    return EventStatus.APPLIED
