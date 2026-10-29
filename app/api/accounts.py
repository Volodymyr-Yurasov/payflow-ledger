from datetime import UTC, datetime

from flask import Blueprint

from app.core.errors import error_response
from app.core.money import format_amount
from app.extensions import services
from app.services.ledger import get_balance, list_transactions

bp = Blueprint("accounts", __name__)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


@bp.get("/accounts/<account_id>/balance")
def balance(account_id: str):
    with services().session_factory() as session:
        result = get_balance(session, account_id)
    if result is None:
        return error_response(404, "account not found")
    return {
        "account_id": result.account_id,
        "currency": result.currency,
        "available": format_amount(result.available),
        "pending": format_amount(result.pending),
    }


@bp.get("/accounts/<account_id>/transactions")
def transactions(account_id: str):
    with services().session_factory() as session:
        items = list_transactions(session, account_id)
    if items is None:
        return error_response(404, "account not found")
    return {
        "items": [
            {
                "authorization_id": item.authorization_id,
                "merchant": item.merchant,
                "currency": item.currency,
                "status": item.status,
                "authorized_amount": (
                    format_amount(item.authorized_amount)
                    if item.authorized_amount is not None
                    else None
                ),
                "captured_amount": format_amount(item.captured_amount),
                "refunded_amount": format_amount(item.refunded_amount),
                "created_at": _iso(item.created_at),
            }
            for item in items
        ]
    }
