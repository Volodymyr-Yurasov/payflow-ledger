"""PayFlow request signing: hex(HMAC_SHA256(secret, raw_body))."""

from __future__ import annotations

import hashlib
import hmac


def compute_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Check the signature against the *raw* bytes, before any JSON parsing.

    Re-serializing the parsed JSON would change whitespace/key order and break the
    HMAC, so the exact bytes received are what gets verified.
    """
    if not header:
        return False
    expected = compute_signature(secret, body).encode()
    # Constant-time comparison, so response timing doesn't leak how many chars matched.
    return hmac.compare_digest(expected, header.strip().lower().encode())
