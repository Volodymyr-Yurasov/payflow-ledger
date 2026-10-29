import logging

from sqlalchemy.orm import Session

from app.models import EventStatus
from app.schemas.events import AuthorizationCapturedData, Event
from app.services.handlers.common import (
    Rejected,
    load_authorization,
    lock_account,
    refresh_status,
)

log = logging.getLogger(__name__)


def apply(session: Session, event: Event[AuthorizationCapturedData]) -> str:
    data = event.data
    account = lock_account(session, data.account_id, data.currency)
    auth = load_authorization(session, account, data.authorization_id, event.created_at)

    if auth.captured_amount is not None:
        if auth.captured_amount == data.amount:
            return EventStatus.NOOP
        raise Rejected(
            f"authorization {auth.id} already captured for {auth.captured_amount};"
            f" got a second capture of {data.amount}"
        )

    if auth.reversed_at is not None:
        # Contradiction from PayFlow. The capture wins because money actually moved;
        # the reversal facts stay on the row for investigation.
        log.error(
            "capture received for a reversed authorization; capture wins",
            extra={"authorization_id": auth.id, "event_id": event.id},
        )

    # The amount may differ from the authorized one (tips, fuel, hotels): that's fine,
    # the pending block is released in full either way.
    auth.captured_amount = data.amount
    auth.captured_at = event.created_at
    refresh_status(auth)
    return EventStatus.APPLIED
