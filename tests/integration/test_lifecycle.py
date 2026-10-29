"""Authorization lifecycle rules from the PayFlow docs, and how contradictions are handled."""

from tests.helpers import captured, created, funded, post_event, refund, reversed_, snapshot


def setup_auth(client, authorized="100.00"):
    post_event(client, funded("evt_f", "1000.00"))
    post_event(client, created("evt_a", "auth_1", authorized))


def test_capture_above_authorized_amount_tips(client):
    setup_auth(client, "100.00")
    post_event(client, captured("evt_c", "auth_1", "118.40"))
    balance, [item] = snapshot(client)
    assert balance["pending"] == "0.00"  # block released in full
    assert balance["available"] == "881.60"
    assert item["authorized_amount"] == "100.00"
    assert item["captured_amount"] == "118.40"


def test_capture_below_authorized_amount(client):
    setup_auth(client, "100.00")
    post_event(client, captured("evt_c", "auth_1", "60.00"))
    balance, [item] = snapshot(client)
    assert balance["pending"] == "0.00"
    assert balance["available"] == "940.00"
    assert item["captured_amount"] == "60.00"


def test_pending_authorization_blocks_funds(client):
    setup_auth(client, "100.00")
    balance, [item] = snapshot(client)
    assert item["status"] == "pending"
    assert balance["pending"] == "100.00"
    assert balance["available"] == "900.00"


def test_reversal_releases_the_block(client):
    setup_auth(client, "100.00")
    post_event(client, reversed_("evt_r", "auth_1", "100.00"))
    balance, [item] = snapshot(client)
    assert item["status"] == "reversed"
    assert item["captured_amount"] == "0.00"
    assert balance["available"] == "1000.00"


def test_multiple_refunds_are_summed(client):
    setup_auth(client)
    post_event(client, captured("evt_c", "auth_1", "100.00"))
    post_event(client, refund("evt_r1", "re_1", "auth_1", "10.00"))
    post_event(client, refund("evt_r2", "re_2", "auth_1", "15.50"))
    balance, [item] = snapshot(client)
    assert item["refunded_amount"] == "25.50"
    assert balance["available"] == "925.50"


def test_refunds_above_the_captured_amount_still_count(client):
    # Refunds are verified PayFlow facts: recorded in full, only logged as unusual.
    setup_auth(client)
    post_event(client, captured("evt_c", "auth_1", "50.00"))
    post_event(client, refund("evt_r1", "re_1", "auth_1", "40.00"))
    post_event(client, refund("evt_r2", "re_2", "auth_1", "30.00"))
    balance, [item] = snapshot(client)
    assert item["refunded_amount"] == "70.00"
    assert balance["available"] == "1020.00"


def test_second_capture_with_same_amount_is_a_noop(client):
    setup_auth(client)
    post_event(client, captured("evt_c1", "auth_1", "100.00"))
    response = post_event(client, captured("evt_c2", "auth_1", "100.00"))
    assert response.get_json()["outcome"] == "duplicate"
    assert snapshot(client)[0]["available"] == "900.00"


def test_second_capture_with_different_amount_is_quarantined(client, db):
    setup_auth(client)
    post_event(client, captured("evt_c1", "auth_1", "100.00"))
    response = post_event(client, captured("evt_c2", "auth_1", "80.00"))
    assert response.status_code == 200
    assert response.get_json()["outcome"] == "quarantined"
    [(error,)] = db("SELECT error FROM webhook_events WHERE id = 'evt_c2'")
    assert "already captured" in error
    assert snapshot(client)[0]["available"] == "900.00"


def test_conflicting_second_create_is_quarantined(client):
    setup_auth(client, "100.00")
    response = post_event(client, created("evt_a2", "auth_1", "999.00"))
    assert response.get_json()["outcome"] == "quarantined"
    assert snapshot(client)[0]["pending"] == "100.00"


def test_identical_second_create_and_reversal_are_noops(client):
    setup_auth(client, "100.00")
    assert post_event(client, created("evt_a2", "auth_1", "100.00")).get_json()[
        "outcome"
    ] == "duplicate"
    post_event(client, reversed_("evt_r1", "auth_1", "100.00"))
    assert post_event(client, reversed_("evt_r2", "auth_1", "100.00")).get_json()[
        "outcome"
    ] == "duplicate"
    assert post_event(client, reversed_("evt_r3", "auth_1", "1.00")).get_json()[
        "outcome"
    ] == "quarantined"


def test_authorization_cannot_move_between_accounts(client):
    setup_auth(client)
    post_event(client, funded("evt_f2", "50.00", account="acc_2"))
    response = post_event(client, captured("evt_c", "auth_1", "10.00", account="acc_2"))
    assert response.get_json()["outcome"] == "quarantined"
    response = post_event(client, refund("evt_r", "re_1", "auth_1", "10.00", account="acc_2"))
    assert response.get_json()["outcome"] == "quarantined"
    assert snapshot(client, "acc_2")[0]["available"] == "50.00"


def test_accounts_are_isolated(client):
    post_event(client, funded("evt_1", "100.00", account="acc_1"))
    post_event(client, funded("evt_2", "200.00", account="acc_2", currency="EUR"))
    post_event(client, created("evt_3", "auth_9", "50.00", account="acc_2", currency="EUR"))

    assert snapshot(client, "acc_1") == (
        {"account_id": "acc_1", "currency": "USD", "available": "100.00", "pending": "0.00"},
        [],
    )
    balance, [item] = snapshot(client, "acc_2")
    assert balance == {
        "account_id": "acc_2", "currency": "EUR", "available": "150.00", "pending": "50.00"
    }
    assert item["currency"] == "EUR"
