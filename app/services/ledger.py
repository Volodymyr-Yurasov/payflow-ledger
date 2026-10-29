"""Read side: balances and transactions, aggregated from stored facts at read time.

There are no running counters that could drift; every number is a SUM over rows that
were each written exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, Authorization, Funding, Refund
from app.services.handlers.status import AuthStatus


@dataclass(frozen=True)
class Balance:
    account_id: str
    currency: str
    available: Decimal
    pending: Decimal


@dataclass(frozen=True)
class Transaction:
    authorization_id: str
    merchant: str | None
    currency: str
    status: str
    authorized_amount: Decimal | None  # None until authorization.created arrives
    captured_amount: Decimal
    refunded_amount: Decimal
    created_at: datetime | None


def _open_account(session: Session, account_id: str) -> Account | None:
    """Accounts become visible with their first account.funded event."""
    account = session.get(Account, account_id)
    if account is None or account.opened_at is None:
        return None
    return account


def _total(column, *conditions):
    return select(func.coalesce(func.sum(column), 0)).where(*conditions).scalar_subquery()


def get_balance(session: Session, account_id: str) -> Balance | None:
    account = _open_account(session, account_id)
    if account is None:
        return None

    # One statement, so all four sums come from the same snapshot.
    funded, pending, captured, refunded = session.execute(
        select(
            _total(Funding.amount, Funding.account_id == account_id),
            _total(
                Authorization.authorized_amount,
                Authorization.account_id == account_id,
                Authorization.status == AuthStatus.PENDING,
            ),
            _total(
                Authorization.captured_amount,
                Authorization.account_id == account_id,
                Authorization.status == AuthStatus.CAPTURED,
            ),
            _total(Refund.amount, Refund.account_id == account_id),
        )
    ).one()

    return Balance(
        account_id=account.id,
        currency=account.currency,
        # May be negative: PayFlow approves spending, we only record it.
        available=funded - pending - captured + refunded,
        pending=pending,
    )


def list_transactions(session: Session, account_id: str) -> list[Transaction] | None:
    if _open_account(session, account_id) is None:
        return None

    refunded = (
        select(Refund.authorization_id, func.sum(Refund.amount).label("total"))
        .where(Refund.account_id == account_id)
        .group_by(Refund.authorization_id)
        .subquery()
    )
    rows = session.execute(
        select(Authorization, refunded.c.total)
        .outerjoin(refunded, refunded.c.authorization_id == Authorization.id)
        .where(Authorization.account_id == account_id)
        .order_by(
            func.coalesce(Authorization.created_at, Authorization.first_seen_at),
            Authorization.id,
        )
    ).all()

    return [
        Transaction(
            authorization_id=auth.id,
            merchant=auth.merchant,
            currency=auth.currency,
            status=auth.status,
            authorized_amount=auth.authorized_amount,
            captured_amount=auth.captured_amount or Decimal(0),
            refunded_amount=refunded_total or Decimal(0),
            created_at=auth.created_at,
        )
        for auth, refunded_total in rows
    ]
