from flask import Blueprint
from sqlalchemy import text

from app.extensions import services

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    svc = services()
    with svc.engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    # Redis is optional (fail-open), so its state is reported but never fails the check.
    return {"status": "ok", "redis": svc.shield.status()}
