"""The HTTP contract: the assignment's expected results and the response-code policy."""

from tests.helpers import (
    EXPECTED_BALANCE,
    EXPECTED_TRANSACTIONS,
    created,
    funded,
    post_event,
    snapshot,
)


def test_happy_path_matches_the_assignment(client, happy_path):
    for event in happy_path:
        response = post_event(client, event)
        assert response.status_code == 200, response.get_json()
        assert response.get_json() == {"status": "ok", "outcome": "applied"}

    assert snapshot(client) == (EXPECTED_BALANCE, EXPECTED_TRANSACTIONS)


def test_unknown_account_is_404(client):
    assert client.get("/accounts/nope/balance").status_code == 404
    assert client.get("/accounts/nope/transactions").status_code == 404


def test_account_without_funding_is_not_visible_yet(client):
    post_event(client, created("evt_1", "auth_1", "10.00"))
    assert snapshot(client) == (404, 404)


def test_unknown_event_type_is_acknowledged_stored_and_ignored(client, db):
    post_event(client, funded("evt_1", "100.00"))
    response = post_event(
        client,
        {"id": "evt_2", "type": "card.frozen", "created_at": "2026-10-19T10:00:00Z",
         "data": {"account_id": "acc_1", "card_id": "card_9"}},
    )
    assert response.status_code == 200
    assert response.get_json()["outcome"] == "ignored"
    assert db("SELECT status, type FROM webhook_events WHERE id = 'evt_2'") == [
        ("ignored", "card.frozen")
    ]
    assert snapshot(client)[0]["available"] == "100.00"


def test_unknown_event_type_with_any_shape_is_ignored(client):
    response = post_event(client, {"id": "evt_1", "type": "something.new", "data": [1, 2]})
    assert response.status_code == 200
    assert response.get_json()["outcome"] == "ignored"


def test_invalid_signature_is_401_and_nothing_is_stored(client, db, redis_client):
    for signature in ["", "deadbeef", "0" * 64]:
        response = post_event(client, funded("evt_1", "100.00"), signature=signature)
        assert response.status_code == 401
    response = post_event(client, funded("evt_1", "100.00"), secret="whsec_wrong")
    assert response.status_code == 401
    response = client.post("/webhooks", data=b"{}", headers={"Content-Type": "application/json"})
    assert response.status_code == 401

    assert db("SELECT count(*) FROM webhook_events") == [(0,)]
    if redis_client is not None:
        assert redis_client.keys("*") == []


def test_signature_must_match_the_raw_body(client):
    body = b'{"id":"evt_1","type":"account.funded"}'
    other = b'{"id": "evt_1", "type": "account.funded"}'  # same JSON, different bytes
    from tests.helpers import sign

    assert post_event(client, body=other, signature=sign(body)).status_code == 401


def test_unparseable_body_is_400_and_nothing_is_stored(client, db):
    for body in [b"not json", b"[]", b'"x"', b'{"type":"account.funded"}',
                 b'{"id":7,"type":"account.funded"}', b"\xff\xfe"]:
        response = post_event(client, body=body)
        assert response.status_code == 400, body
    assert db("SELECT count(*) FROM webhook_events") == [(0,)]


def test_oversized_body_is_413(client):
    event = funded("evt_1", "1.00")
    event["padding"] = "x" * (70 * 1024)
    assert post_event(client, event).status_code == 413


def test_invalid_data_is_quarantined_not_applied(client, db):
    bad = funded("evt_1", "abc")
    response = post_event(client, bad)
    assert response.status_code == 200
    assert response.get_json()["outcome"] == "quarantined"

    [(status, error)] = db("SELECT status, error FROM webhook_events WHERE id = 'evt_1'")
    assert status == "rejected"
    assert "amount" in error
    assert db("SELECT count(*) FROM fundings") == [(0,)]


def test_currency_mismatch_is_quarantined(client, db):
    post_event(client, funded("evt_1", "100.00", currency="USD"))
    response = post_event(client, created("evt_2", "auth_1", "10.00", currency="EUR"))
    assert response.get_json()["outcome"] == "quarantined"
    [(error,)] = db("SELECT error FROM webhook_events WHERE id = 'evt_2'")
    assert "EUR" in error and "USD" in error
    balance, transactions = snapshot(client)
    assert balance["available"] == "100.00"
    assert transactions == []


def test_spending_beyond_funds_gives_negative_available(client):
    # PayFlow approves on its own rules; we record, we don't refuse.
    post_event(client, funded("evt_1", "10.00"))
    post_event(client, created("evt_2", "auth_1", "25.00"))
    assert snapshot(client)[0]["available"] == "-15.00"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
