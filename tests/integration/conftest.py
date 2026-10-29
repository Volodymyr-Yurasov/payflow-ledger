"""Integration fixtures: real Postgres and Redis (the compose `tests` service provides both)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import redis
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from app import create_app
from app.config import Config
from tests.helpers import SECRET

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set: integration tests need Postgres")
    if not url.rsplit("/", 1)[-1].endswith("_test"):
        raise RuntimeError(f"refusing to run tests against a non-test database: {url}")
    return url


def make_config(**overrides) -> Config:
    config = Config(
        database_url=_database_url(),
        webhook_secret=SECRET,
        redis_url=os.environ.get("REDIS_URL") or None,
        # Concurrency tests fire many requests at once from one process.
        db_pool_size=20,
        db_max_overflow=20,
        log_level="WARNING",
    )
    return config.with_overrides(**overrides)


@pytest.fixture(scope="session")
def migrated_db():
    """Rebuild the schema from the Alembic migrations, so they're tested too."""
    cfg = AlembicConfig(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _database_url())
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def _build(migrated_db, **overrides):
    app = create_app(make_config(**overrides))
    yield app
    app.extensions["payflow"].close()


@pytest.fixture(scope="session")
def app(migrated_db):
    yield from _build(migrated_db)


@pytest.fixture(scope="session")
def app_without_redis(migrated_db):
    yield from _build(migrated_db, redis_url=None)


@pytest.fixture(scope="session")
def app_with_dead_redis(migrated_db):
    # Nothing listens on port 1: every Redis call fails fast.
    yield from _build(migrated_db, redis_url="redis://127.0.0.1:1/0")


@pytest.fixture(scope="session")
def redis_client():
    url = os.environ.get("REDIS_URL")
    return redis.Redis.from_url(url) if url else None


def reset_state(app, redis_client=None) -> None:
    with app.extensions["payflow"].engine.begin() as conn:
        conn.execute(
            text("TRUNCATE refunds, authorizations, fundings, accounts, webhook_events")
        )
    if redis_client is not None:
        redis_client.flushdb()


@pytest.fixture(autouse=True)
def _clean(app, redis_client):
    reset_state(app, redis_client)


@pytest.fixture
def reset(app, redis_client):
    """For tests that need a clean slate several times (e.g. per Hypothesis example)."""
    return lambda: reset_state(app, redis_client)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def happy_path():
    return json.loads((FIXTURES / "happy_path.json").read_text(encoding="utf-8"))


@pytest.fixture
def db(app):
    """Run raw SQL against the test DB, for asserting on stored state."""

    def query(sql: str, **params):
        with app.extensions["payflow"].engine.connect() as conn:
            return conn.execute(text(sql), params).all()

    return query
