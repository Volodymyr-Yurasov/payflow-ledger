from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.models import Base
from app.services.handlers import HANDLERS
from tests.helpers import created, event, funded, post_event, snapshot


def test_ignored_events_can_be_replayed_once_supported(app, client, db, monkeypatch):
    post_event(client, funded("evt_1", "100.00"))
    top_up = event("evt_2", "account.topped_up", "2026-10-19T11:00:00Z",
                   account_id="acc_1", amount="50.00", currency="USD")
    assert post_event(client, top_up).get_json()["outcome"] == "ignored"
    assert snapshot(client)[0]["available"] == "100.00"

    # "Ship" support for the new type, then replay what we stored.
    monkeypatch.setitem(HANDLERS, "account.topped_up", HANDLERS["account.funded"])
    result = app.test_cli_runner().invoke(args=["events", "replay", "--status", "ignored"])

    assert result.exit_code == 0, result.output
    assert "evt_2: ignored -> applied" in result.output
    assert db("SELECT status FROM webhook_events WHERE id = 'evt_2'") == [("applied",)]
    assert snapshot(client)[0]["available"] == "150.00"


def test_replay_keeps_still_invalid_events_quarantined(app, client):
    post_event(client, funded("evt_1", "100.00", currency="USD"))
    post_event(client, created("evt_2", "auth_1", "10.00", currency="EUR"))

    result = app.test_cli_runner().invoke(args=["events", "replay", "--id", "evt_2"])
    assert result.exit_code == 0, result.output
    assert "evt_2: rejected -> rejected" in result.output
    assert snapshot(client)[1] == []


def test_migrations_match_the_models(app):
    with app.extensions["payflow"].engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
