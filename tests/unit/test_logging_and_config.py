import json
import logging

from app.config import Config
from app.core.logging import JsonFormatter


def test_json_formatter_includes_extra_fields():
    record = logging.makeLogRecord(
        {"name": "x", "levelname": "INFO", "msg": "hello %s", "args": ("world",)}
    )
    record.event_id = "evt_1"
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "hello world"
    assert line["event_id"] == "evt_1"
    assert line["level"] == "INFO"


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    monkeypatch.setenv("PAYFLOW_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("DB_POOL_SIZE", "3")
    config = Config.from_env()
    assert config.redis_url is None
    assert config.db_pool_size == 3
    assert config.statement_timeout_ms < 10_000  # under PayFlow's delivery timeout
    assert config.redis_lock_ttl_ms > config.statement_timeout_ms
    assert config.redis_done_ttl_s > 72 * 3600
