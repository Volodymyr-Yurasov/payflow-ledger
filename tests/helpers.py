"""Shared test helpers: event builders, a sender that signs exactly like PayFlow's, and
the expected happy-path state from the assignment."""

from __future__ import annotations

import json
from typing import Any

from app.core.signature import compute_signature

SECRET = "whsec_test_123"

EXPECTED_BALANCE = {
    "account_id": "acc_1",
    "currency": "USD",
    "available": "585.00",
    "pending": "15.00",
}


def _tx(auth_id, merchant, status, authorized, captured, refunded, created_at):
    return {
        "authorization_id": auth_id,
        "merchant": merchant,
        "currency": "USD",
        "status": status,
        "authorized_amount": authorized,
        "captured_amount": captured,
        "refunded_amount": refunded,
        "created_at": created_at,
    }


EXPECTED_TRANSACTIONS = [
    _tx("auth_100", "AWS", "captured", "125.50", "125.50", "25.50", "2026-10-19T10:01:00Z"),
    _tx("auth_101", "Uber", "reversed", "40.00", "0.00", "0.00", "2026-10-19T10:02:00Z"),
    _tx("auth_102", "Hilton", "captured", "300.00", "300.00", "0.00", "2026-10-19T10:10:00Z"),
    _tx("auth_103", "Slack", "pending", "15.00", "0.00", "0.00", "2026-10-19T12:30:00Z"),
]


def encode(event: dict[str, Any]) -> bytes:
    """Serialize the way PayFlowEventsSender.py does."""
    return json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode()


def sign(body: bytes, secret: str = SECRET) -> str:
    return compute_signature(secret, body)


def post_event(client, event=None, *, body=None, secret=SECRET, signature=None, headers=None):
    if body is None:
        body = encode(event)
    all_headers = {
        "Content-Type": "application/json",
        "X-PayFlow-Signature": sign(body, secret) if signature is None else signature,
    }
    all_headers.update(headers or {})
    return client.post("/webhooks", data=body, headers=all_headers)


def snapshot(client, account_id: str = "acc_1"):
    """(balance, transactions) as the API returns them, or the 404 status codes."""
    balance = client.get(f"/accounts/{account_id}/balance")
    transactions = client.get(f"/accounts/{account_id}/transactions")
    return (
        balance.get_json() if balance.status_code == 200 else balance.status_code,
        transactions.get_json()["items"] if transactions.status_code == 200 else 404,
    )


# --- event builders ----------------------------------------------------------------


def event(event_id: str, event_type: str, created_at: str, **data: Any) -> dict[str, Any]:
    return {"id": event_id, "type": event_type, "created_at": created_at, "data": data}


def funded(event_id, amount, *, account="acc_1", currency="USD", at="2026-10-19T10:00:00Z"):
    return event(event_id, "account.funded", at,
                 account_id=account, amount=amount, currency=currency)


def created(event_id, auth_id, amount, *, merchant="AWS", account="acc_1", currency="USD",
            at="2026-10-19T10:01:00Z"):
    return event(event_id, "authorization.created", at, account_id=account,
                 authorization_id=auth_id, amount=amount, currency=currency, merchant=merchant)


def captured(event_id, auth_id, amount, *, account="acc_1", currency="USD",
             at="2026-10-19T10:05:00Z"):
    return event(event_id, "authorization.captured", at, account_id=account,
                 authorization_id=auth_id, amount=amount, currency=currency)


def reversed_(event_id, auth_id, amount, *, account="acc_1", currency="USD",
              at="2026-10-19T10:06:00Z"):
    return event(event_id, "authorization.reversed", at, account_id=account,
                 authorization_id=auth_id, amount=amount, currency=currency)


def refund(event_id, refund_id, auth_id, amount, *, account="acc_1", currency="USD",
           at="2026-10-19T12:00:00Z"):
    return event(event_id, "refund.created", at, account_id=account, refund_id=refund_id,
                 authorization_id=auth_id, amount=amount, currency=currency)
