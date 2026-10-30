import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Authorization, EventStatus, Refund
from app.schemas.events import Event, RefundCreatedData
from app.services.handlers.common import Rejected, lock_account

log = logging.getLogger(__name__)


def apply(session: Session, event: Event[RefundCreatedData]) -> EventStatus:
    data = event.data
    account = lock_account(session, data.account_id, data.currency)

    existing = session.get(Refund, data.refund_id)
    if existing is not None:
        # Same refund re-sent under a new event id: count it once.
        if existing.amount == data.amount and existing.authorization_id == data.authorization_id:
            return EventStatus.NOOP
        raise Rejected(
            f"refund {data.refund_id} already recorded as {existing.amount}"
            f" for {existing.authorization_id}"
        )

    auth = session.get(Authorization, data.authorization_id)
    if auth is not None and auth.account_id != account.id:
        raise Rejected(
            f"refund {data.refund_id} targets authorization {auth.id}"
            f" of account {auth.account_id}"
        )

    session.add(
        Refund(
            id=data.refund_id,
            authorization_id=data.authorization_id,
            account_id=account.id,
            amount=data.amount,
            event_id=event.id,
            created_at=event.created_at,
        )
    )

    # Refunds are verified PayFlow facts and always count. Unusual ones are only logged.
    if auth is None or auth.captured_amount is None:
        log.warning(
            "refund received before its capture",
            extra={"refund_id": data.refund_id, "authorization_id": data.authorization_id},
        )
    else:
        refunded = session.scalar(
            select(func.sum(Refund.amount)).where(Refund.authorization_id == auth.id)
        )
        if refunded > auth.captured_amount:
            log.warning(
                "refunds exceed the captured amount",
                extra={
                    "authorization_id": auth.id,
                    "captured": str(auth.captured_amount),
                    "refunded": str(refunded),
                },
            )
    return EventStatus.APPLIED
