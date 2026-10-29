import json

import pytest

from app.core.signature import compute_signature, verify_signature
from tests.helpers import SECRET, encode

BODY = encode({"id": "evt_1", "type": "account.funded", "data": {"amount": "1.00"}})


def test_valid_signature_is_accepted():
    assert verify_signature(SECRET, BODY, compute_signature(SECRET, BODY))


def test_signature_is_case_and_whitespace_tolerant():
    assert verify_signature(SECRET, BODY, f"  {compute_signature(SECRET, BODY).upper()} ")


@pytest.mark.parametrize("header", [None, "", "not-hex", "0" * 64, "ü" * 64])
def test_missing_or_garbage_signature_is_rejected(header):
    assert not verify_signature(SECRET, BODY, header)


def test_wrong_secret_is_rejected():
    assert not verify_signature(SECRET, BODY, compute_signature("whsec_other", BODY))


def test_one_changed_byte_is_rejected():
    tampered = BODY.replace(b"1.00", b"9.00")
    assert not verify_signature(SECRET, tampered, compute_signature(SECRET, BODY))


def test_reserialized_json_is_rejected():
    # Same JSON value, different bytes: the signature covers raw bytes, not the value.
    reserialized = json.dumps(json.loads(BODY), indent=2).encode()
    assert not verify_signature(SECRET, reserialized, compute_signature(SECRET, BODY))
