from sqlalchemy.orm import Session

from app.models import EventStatus
from app.schemas.events import AuthorizationReversedData, Event
from app.services.handlers.common import (
    Rejected,
    load_authorization,
    lock_account,
    refresh_status,
)


def apply(session: Session, event: Event[AuthorizationReversedData]) -> EventStatus:
    data = event.data
    account = lock_account(session, data.account_id, data.currency)
    auth = load_authorization(session, account, data.authorization_id, event.created_at)

    if auth.captured_amount is not None:
        # Mirror of the capture handler: a capture beats a reversal in either order.
        raise Rejected(f"authorization {auth.id} is already captured; reversal ignored")

    if auth.reversed_at is not None:
        if auth.reversed_amount == data.amount:
            return EventStatus.NOOP
        raise Rejected(
            f"authorization {auth.id} already reversed for {auth.reversed_amount};"
            f" got a second reversal of {data.amount}"
        )

    auth.reversed_amount = data.amount
    auth.reversed_at = event.created_at
    refresh_status(auth)
    return EventStatus.APPLIED
