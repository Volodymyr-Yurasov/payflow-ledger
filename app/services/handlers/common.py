"""Building blocks shared by the per-type handlers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Account, Authorization
from app.services.handlers.status import AuthStatus, derive_status


class Rejected(Exception):
    """The event is well-formed but can't be applied (it contradicts what we know).

    It gets quarantined: stored with the reason, no effect on balances, answered 200.
    """


def lock_account(session: Session, account_id: str, currency: str) -> Account:
    """Create the account row if needed and lock it for the rest of the transaction.

    Every event for an account takes this lock, so events of one account are applied
    one at a time (no lost updates), while different accounts proceed in parallel.
    The first event to mention an account pins its currency.
    """
    session.execute(
        pg_insert(Account)
        .values(id=account_id, currency=currency)
        .on_conflict_do_nothing(index_elements=[Account.id])
    )
    account = session.execute(
        select(Account)
        .where(Account.id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if account.currency != currency:
        raise Rejected(
            f"currency {currency} does not match account {account_id} currency {account.currency}"
        )
    return account


def load_authorization(
    session: Session, account: Account, authorization_id: str, seen_at: datetime
) -> Authorization:
    """Fetch the authorization row (locked), creating an empty one if this is the
    first event we've seen for it. Any lifecycle event may be the first to arrive."""
    auth = session.get(
        Authorization, authorization_id, with_for_update=True, populate_existing=True
    )
    if auth is None:
        auth = Authorization(
            id=authorization_id,
            account_id=account.id,
            currency=account.currency,
            status=AuthStatus.PENDING,
            first_seen_at=seen_at,
        )
        session.add(auth)
        return auth
    if auth.account_id != account.id:
        raise Rejected(f"authorization {authorization_id} belongs to account {auth.account_id}")
    auth.first_seen_at = min(auth.first_seen_at, seen_at)
    return auth


def refresh_status(auth: Authorization) -> None:
    auth.status = derive_status(auth.captured_amount, auth.reversed_at)
