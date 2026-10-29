"""At-least-once delivery: duplicates never change the ledger twice, and the Redis
shield only ever makes things faster, never wrong."""

import pytest

from app.services.handlers import HANDLERS, Handler
from tests.helpers import (
    EXPECTED_BALANCE,
    EXPECTED_TRANSACTIONS,
    funded,
    post_event,
    refund,
    snapshot,
)


def test_same_event_delivered_many_times_is_applied_once(client, db):
    event = funded("evt_1", "100.00")
    outcomes = [post_event(client, event).get_json()["outcome"] for _ in range(5)]
    assert outcomes == ["applied"] + ["duplicate"] * 4
    assert db("SELECT count(*) FROM fundings") == [(1,)]
    assert snapshot(client)[0]["available"] == "100.00"


def test_whole_happy_path_delivered_three_times_interleaved(client, happy_path):
    for event in happy_path + list(reversed(happy_path)) + happy_path:
        assert post_event(client, event).status_code == 200
    assert snapshot(client) == (EXPECTED_BALANCE, EXPECTED_TRANSACTIONS)


def test_same_id_with_different_payload_keeps_the_first(client, db):
    post_event(client, funded("evt_1", "100.00"))
    # Checked even though the id is already in the Redis "done" cache: the cache stores
    # the payload hash, so different content falls through to Postgres every time.
    for _ in range(2):
        response = post_event(client, funded("evt_1", "999.00"))
        assert response.status_code == 200
        assert response.get_json()["outcome"] == "duplicate_mismatch"
    assert post_event(client, funded("evt_1", "100.00")).get_json()["outcome"] == "duplicate"
    assert snapshot(client)[0]["available"] == "100.00"


def test_same_refund_under_a_new_event_id_is_counted_once(client, db):
    post_event(client, funded("evt_1", "100.00"))
    post_event(client, refund("evt_2", "re_1", "auth_1", "5.00"))
    response = post_event(client, refund("evt_3", "re_1", "auth_1", "5.00"))
    assert response.get_json()["outcome"] == "duplicate"
    assert db("SELECT status FROM webhook_events WHERE id = 'evt_3'") == [("noop",)]
    assert snapshot(client)[0]["available"] == "105.00"


def test_conflicting_refund_under_the_same_refund_id_is_quarantined(client):
    post_event(client, funded("evt_1", "100.00"))
    post_event(client, refund("evt_2", "re_1", "auth_1", "5.00"))
    response = post_event(client, refund("evt_3", "re_1", "auth_1", "7.00"))
    assert response.get_json()["outcome"] == "quarantined"
    assert snapshot(client)[0]["available"] == "105.00"


def test_crash_mid_apply_loses_nothing(client, db, redis_client, monkeypatch):
    """If processing dies after writing to the ledger, the whole transaction (including
    the 'seen' marker) rolls back, so PayFlow's retry is applied normally."""
    original = HANDLERS["account.funded"]

    def crash_after_write(session, event):
        original.apply(session, event)
        session.flush()
        raise RuntimeError("simulated crash after the ledger write")

    monkeypatch.setitem(
        HANDLERS, "account.funded", Handler(original.data_model, crash_after_write)
    )
    event = funded("evt_1", "100.00")
    assert post_event(client, event).status_code == 500
    assert db("SELECT count(*) FROM webhook_events") == [(0,)]
    assert db("SELECT count(*) FROM fundings") == [(0,)]
    if redis_client is not None:
        assert redis_client.keys("*") == []  # not marked done, lock released

    monkeypatch.undo()
    response = post_event(client, event)
    assert response.get_json()["outcome"] == "applied"
    assert snapshot(client)[0]["available"] == "100.00"


def test_database_outage_is_503_so_payflow_retries(app, client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def down(work):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(app.extensions["payflow"].tx, "run", down)
    assert post_event(client, funded("evt_1", "100.00")).status_code == 503


def test_done_cache_answers_duplicates_without_touching_the_database(
    app, client, redis_client, monkeypatch
):
    if redis_client is None:
        pytest.skip("needs Redis")
    event = funded("evt_1", "100.00")
    post_event(client, event)

    def database_must_not_be_used(work):
        raise AssertionError("duplicate should have been answered from Redis")

    monkeypatch.setattr(app.extensions["payflow"].tx, "run", database_must_not_be_used)
    response = post_event(client, event)
    assert response.status_code == 200
    assert response.get_json()["outcome"] == "duplicate"


def test_event_in_flight_elsewhere_gets_409_then_succeeds(client, db, redis_client):
    if redis_client is None:
        pytest.skip("needs Redis")
    redis_client.set("pf:evt:evt_1:lock", "another-request", px=10_000)

    response = post_event(client, funded("evt_1", "100.00"))
    assert response.status_code == 409
    assert response.headers["Retry-After"] == "2"
    assert db("SELECT count(*) FROM webhook_events") == [(0,)]

    redis_client.delete("pf:evt:evt_1:lock")
    assert post_event(client, funded("evt_1", "100.00")).get_json()["outcome"] == "applied"


@pytest.mark.parametrize("app_fixture", ["app_with_dead_redis", "app_without_redis"])
def test_correct_without_redis(request, app_fixture, happy_path):
    """Fail-open: with Redis down (or disabled), Postgres alone keeps everything exact."""
    client = request.getfixturevalue(app_fixture).test_client()
    for event in happy_path + happy_path:
        assert post_event(client, event).status_code == 200
    assert snapshot(client) == (EXPECTED_BALANCE, EXPECTED_TRANSACTIONS)
    assert client.get("/health").status_code == 200
