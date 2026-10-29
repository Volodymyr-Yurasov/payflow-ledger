"""Delivery order is not guaranteed: every order must converge to the same state."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.helpers import (
    EXPECTED_BALANCE,
    EXPECTED_TRANSACTIONS,
    captured,
    created,
    funded,
    post_event,
    refund,
    reversed_,
    snapshot,
)


@settings(
    max_examples=75,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(order=st.permutations(range(9)))
def test_every_delivery_order_of_the_happy_path_converges(client, reset, happy_path, order):
    reset()
    for index in order:
        assert post_event(client, happy_path[index]).status_code == 200
    assert snapshot(client) == (EXPECTED_BALANCE, EXPECTED_TRANSACTIONS)


def test_fully_reversed_order(client, happy_path):
    for event in reversed(happy_path):
        assert post_event(client, event).status_code == 200
    assert snapshot(client) == (EXPECTED_BALANCE, EXPECTED_TRANSACTIONS)


def test_capture_before_create_fills_one_row(client, db):
    post_event(client, funded("evt_1", "500.00"))
    post_event(client, captured("evt_3", "auth_1", "130.00"))

    _, [item] = snapshot(client)
    assert item["status"] == "captured"
    assert item["authorized_amount"] is None  # not known yet
    assert item["merchant"] is None
    assert item["captured_amount"] == "130.00"

    post_event(client, created("evt_2", "auth_1", "125.50"))
    balance, [item] = snapshot(client)
    assert db("SELECT count(*) FROM authorizations") == [(1,)]
    assert item["status"] == "captured"  # a late `created` doesn't reopen it
    assert item["authorized_amount"] == "125.50"
    assert item["merchant"] == "AWS"
    assert item["created_at"] == "2026-10-19T10:01:00Z"
    assert balance == {**EXPECTED_BALANCE, "available": "370.00", "pending": "0.00"}


def test_refund_then_capture_then_create(client):
    post_event(client, funded("evt_1", "500.00"))
    post_event(client, refund("evt_4", "re_1", "auth_1", "20.00"))
    assert snapshot(client)[0]["available"] == "520.00"  # counted as soon as it arrives
    post_event(client, captured("evt_3", "auth_1", "100.00"))
    post_event(client, created("evt_2", "auth_1", "100.00"))

    balance, [item] = snapshot(client)
    assert balance["available"] == "420.00"
    assert item["refunded_amount"] == "20.00"
    assert item["status"] == "captured"


def test_reverse_before_create(client):
    post_event(client, funded("evt_1", "100.00"))
    post_event(client, reversed_("evt_3", "auth_1", "40.00"))
    post_event(client, created("evt_2", "auth_1", "40.00"))

    balance, [item] = snapshot(client)
    assert item["status"] == "reversed"
    assert item["authorized_amount"] == "40.00"
    assert balance["pending"] == "0.00"
    assert balance["available"] == "100.00"


def test_events_before_account_funded(client, happy_path):
    for event in happy_path[1:]:
        post_event(client, event)
    assert snapshot(client) == (404, 404)

    post_event(client, happy_path[0])
    assert snapshot(client) == (EXPECTED_BALANCE, EXPECTED_TRANSACTIONS)


def test_capture_and_reversal_contradiction_ends_the_same_in_both_orders(client, reset):
    capture = captured("evt_c", "auth_1", "50.00")
    reversal = reversed_("evt_r", "auth_1", "50.00")
    results = []
    for first, second in [(capture, reversal), (reversal, capture)]:
        reset()
        post_event(client, funded("evt_1", "100.00"))
        post_event(client, created("evt_2", "auth_1", "50.00"))
        post_event(client, first)
        post_event(client, second)
        results.append(snapshot(client))

    assert results[0] == results[1]
    balance, [item] = results[0]
    assert item["status"] == "captured"  # money moved: capture wins
    assert balance["available"] == "50.00"
