from __future__ import annotations

from flask import Flask

from app.config import Config
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.extensions import build_services


def create_app(config: Config | None = None) -> Flask:
    config = config or Config.from_env()
    configure_logging(config.log_level)

    app = Flask(__name__)
    # Werkzeug answers 413 for larger bodies before we read them.
    app.config["MAX_CONTENT_LENGTH"] = config.max_body_bytes
    app.json.sort_keys = False
    app.extensions["payflow"] = build_services(config)

    from app.api import accounts, docs, health, webhooks
    from app.cli.replay import events_cli

    app.register_blueprint(webhooks.bp)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(health.bp)
    app.register_blueprint(docs.bp)
    app.cli.add_command(events_cli)
    register_error_handlers(app)
    return app
