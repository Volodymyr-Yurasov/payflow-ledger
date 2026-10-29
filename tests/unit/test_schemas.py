from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.envelope import Envelope
from app.schemas.events import (
    AccountFundedData,
    AuthorizationCreatedData,
    RefundCreatedData,
    parse_event,
)
from app.services.ingest import payload_digest
from tests.helpers import created, funded, refund


def test_parses_a_known_event():
    event = parse_event(created("evt_1", "auth_1", "125.50"), AuthorizationCreatedData)
    assert event.id == "evt_1"
    assert event.created_at.isoformat() == "2026-10-19T10:01:00+00:00"
    assert event.data.amount == Decimal("125.50")
    assert event.data.merchant == "AWS"


def test_unknown_extra_fields_are_ignored():
    payload = funded("evt_1", "10.00")
    payload["data"]["new_field_from_payflow"] = {"x": 1}
    assert parse_event(payload, AccountFundedData).data.amount == Decimal("10.00")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", 10.0),
        ("amount", "abc"),
        ("currency", "usd"),
        ("currency", "US"),
        ("account_id", ""),
        ("account_id", 123),
        ("refund_id", None),
    ],
)
def test_invalid_data_is_rejected(field, value):
    payload = refund("evt_1", "re_1", "auth_1", "5.00")
    payload["data"][field] = value
    with pytest.raises(ValidationError):
        parse_event(payload, RefundCreatedData)


@pytest.mark.parametrize("created_at", [None, "yesterday", "2026-10-19T10:00:00"])
def test_created_at_must_be_a_timezone_aware_timestamp(created_at):
    payload = funded("evt_1", "10.00")
    payload["created_at"] = created_at
    with pytest.raises(ValidationError):
        parse_event(payload, AccountFundedData)


def test_data_must_be_an_object():
    payload = funded("evt_1", "10.00")
    payload["data"] = ["not", "an", "object"]
    with pytest.raises(ValidationError):
        parse_event(payload, AccountFundedData)


@pytest.mark.parametrize(
    "payload",
    [{"type": "x"}, {"id": "e"}, {"id": 1, "type": "x"}, {"id": "", "type": "x"}, []],
)
def test_envelope_needs_string_id_and_type(payload):
    with pytest.raises(ValidationError):
        Envelope.model_validate(payload)


def test_payload_digest_ignores_key_order_but_not_values():
    a = {"id": "e", "type": "t", "data": {"x": "1", "y": "2"}}
    b = {"data": {"y": "2", "x": "1"}, "type": "t", "id": "e"}
    c = {"id": "e", "type": "t", "data": {"x": "1", "y": "3"}}
    assert payload_digest(a) == payload_digest(b)
    assert payload_digest(a) != payload_digest(c)
