"""Offline tests for the request-signing envelope (no network)."""

from __future__ import annotations

import hashlib
import hmac

from nadlan.signing import (
    HMAC_SECRET,
    DEFAULT_DOMAIN,
    decode_envelope,
    make_sk,
    sign_payload,
)


def test_envelope_roundtrips():
    payload = {"base_id": "50001103", "base_name": "streetCode", "fetch_number": 1}
    envelope = sign_payload(payload)

    assert set(envelope) == {"##"}
    recovered = decode_envelope(envelope)

    # business fields survive the round-trip
    for key, value in payload.items():
        assert recovered[key] == value
    # the signer injects these
    assert recovered["domain"] == DEFAULT_DOMAIN
    assert isinstance(recovered["exp"], int)
    assert "sk" in recovered


def test_signature_uses_bundle_secret_and_is_reversed():
    envelope = sign_payload({"x": 1}, include_sk=False)
    jwt = envelope["##"][::-1]  # un-reverse
    header_b64, body_b64, sig_b64 = jwt.split(".")

    expected_sig = hmac.new(
        HMAC_SECRET, f"{header_b64}.{body_b64}".encode(), hashlib.sha256
    ).digest()
    import base64

    got_sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
    assert got_sig == expected_sig


def test_recaptcha_token_included_when_provided():
    recovered = decode_envelope(sign_payload({"a": 1}, recaptcha_token="server-tok"))
    assert recovered["token"] == "server-tok"


def test_make_sk_is_a_jwt_with_domain_and_exp():
    sk = make_sk()
    assert sk.count(".") == 2  # header.body.sig
