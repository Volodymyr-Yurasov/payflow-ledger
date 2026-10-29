import json
import logging
import time

from flask import Blueprint, request
from pydantic import ValidationError

from app.core.errors import error_response
from app.core.signature import verify_signature
from app.extensions import services
from app.schemas.envelope import Envelope

log = logging.getLogger(__name__)

bp = Blueprint("webhooks", __name__)

SIGNATURE_HEADER = "X-PayFlow-Signature"


@bp.post("/webhooks")
def receive_webhook():
    started = time.perf_counter()
    svc = services()

    # Raw bytes exactly as received: the signature covers these, not re-serialized JSON.
    raw = request.get_data(cache=False)
    if not verify_signature(svc.config.webhook_secret, raw, request.headers.get(SIGNATURE_HEADER)):
        log.warning("invalid webhook signature", extra={"remote_addr": request.remote_addr})
        return error_response(401, "invalid signature")

    try:
        payload = json.loads(raw)
        envelope = Envelope.model_validate(payload)
    except (ValueError, ValidationError):
        # Without an id we can't store or dedupe it, so this is the one case where a
        # signed request gets a 4xx.
        return error_response(400, "body must be a JSON object with string 'id' and 'type'")

    outcome = svc.ingest.ingest(payload)
    log.info(
        "webhook processed",
        extra={
            "event_id": envelope.id,
            "event_type": envelope.type,
            "outcome": outcome.value,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return {"status": "ok", "outcome": outcome.value}
