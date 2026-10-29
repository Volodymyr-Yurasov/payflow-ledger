"""Long-lived objects (DB engine, Redis client, services), built once per app/process."""

from __future__ import annotations

from dataclasses import dataclass

import redis
from flask import current_app
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Config
from app.core.db import TransactionRunner
from app.services.ingest import IngestService
from app.services.shield import Shield


@dataclass
class Services:
    config: Config
    engine: Engine
    session_factory: sessionmaker[Session]
    tx: TransactionRunner
    shield: Shield
    ingest: IngestService

    def close(self) -> None:
        self.engine.dispose()


def build_services(config: Config) -> Services:
    engine = create_engine(
        config.database_url,
        pool_size=config.db_pool_size,
        max_overflow=config.db_max_overflow,
        # Fail fast (-> 503) rather than queueing past PayFlow's 10s timeout.
        pool_timeout=5,
        pool_pre_ping=True,
    )
    session_factory = sessionmaker(engine, expire_on_commit=False)
    tx = TransactionRunner(
        session_factory,
        statement_timeout_ms=config.statement_timeout_ms,
        lock_timeout_ms=config.lock_timeout_ms,
    )

    redis_client = None
    if config.redis_url:
        redis_client = redis.Redis.from_url(
            config.redis_url,
            socket_timeout=config.redis_socket_timeout_s,
            socket_connect_timeout=config.redis_socket_timeout_s,
        )
    shield = Shield(
        redis_client,
        done_ttl_s=config.redis_done_ttl_s,
        lock_ttl_ms=config.redis_lock_ttl_ms,
    )

    return Services(
        config=config,
        engine=engine,
        session_factory=session_factory,
        tx=tx,
        shield=shield,
        ingest=IngestService(tx, shield),
    )


def services() -> Services:
    return current_app.extensions["payflow"]
