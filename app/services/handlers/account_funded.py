from sqlalchemy.orm import Session

from app.models import EventStatus, Funding
from app.schemas.events import AccountFundedData, Event
from app.services.handlers.common import lock_account


def apply(session: Session, event: Event[AccountFundedData]) -> EventStatus:
    data = event.data
    account = lock_account(session, data.account_id, data.currency)
    session.add(
        Funding(
            event_id=event.id,
            account_id=account.id,
            amount=data.amount,
            created_at=event.created_at,
        )
    )
    # The first funding "creates" the account as far as the API is concerned.
    if account.opened_at is None or event.created_at < account.opened_at:
        account.opened_at = event.created_at
    return EventStatus.APPLIED
