"""Real responses match the schemas in the OpenAPI spec, so the docs can't drift."""

from tests.helpers import (
    assert_matches_schema,
    captured,
    funded,
    post_event,
)


def test_webhook_and_account_responses_match_the_spec(client, happy_path):
    for event in happy_path:
        assert_matches_schema(post_event(client, event).get_json(), "WebhookAck")

    assert_matches_schema(client.get("/accounts/acc_1/balance").get_json(), "Balance")
    assert_matches_schema(
        client.get("/accounts/acc_1/transactions").get_json(), "TransactionList"
    )


def test_unknown_fields_are_null_until_created_arrives(client):
    post_event(client, funded("evt_1", "10.00"))
    post_event(client, captured("evt_2", "auth_1", "25.00"))  # negative available, nulls

    assert_matches_schema(client.get("/accounts/acc_1/balance").get_json(), "Balance")
    assert_matches_schema(
        client.get("/accounts/acc_1/transactions").get_json(), "TransactionList"
    )


def test_error_responses_match_the_spec(client):
    responses = [
        client.get("/accounts/nope/balance"),  # 404
        post_event(client, funded("evt_1", "1.00"), signature="0" * 64),  # 401
        post_event(client, body=b"not json"),  # 400
    ]
    for response in responses:
        assert response.status_code in (400, 401, 404)
        assert_matches_schema(response.get_json(), "Error")


def test_health_matches_the_spec(client):
    assert_matches_schema(client.get("/health").get_json(), "Health")
