"""Offline tests for the request-signing envelope (no network)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

from nadlan import signing
from nadlan.signing import (
    HMAC_SECRET,
    DEFAULT_DOMAIN,
    decode_envelope,
    make_sk,
    sign_payload,
)


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def test_envelope_roundtrips():
    payload = {"base_id": "50001103", "base_name": "streetCode", "fetch_number": 1}
    envelope = sign_payload(payload)

    assert set(envelope) == {"##"}
    recovered = decode_envelope(envelope)

    for key, value in payload.items():
        assert recovered[key] == value
    assert recovered["domain"] == DEFAULT_DOMAIN
    assert isinstance(recovered["exp"], int)
    assert "sk" in recovered


def test_signature_uses_bundle_secret_and_is_reversed():
    envelope = sign_payload({"x": 1}, include_sk=False)
    jwt = envelope["##"][::-1]  # un-reverse
    header_b64, body_b64, sig_b64 = jwt.split(".")

    expected = hmac.new(HMAC_SECRET, f"{header_b64}.{body_b64}".encode(), hashlib.sha256).digest()
    assert _b64url_decode(sig_b64) == expected


def test_recaptcha_token_included_when_provided():
    recovered = decode_envelope(sign_payload({"a": 1}, recaptcha_token="server-tok"))
    assert recovered["token"] == "server-tok"


def test_no_sk_and_no_token_when_omitted():
    recovered = decode_envelope(sign_payload({"a": 1}, include_sk=False))
    assert "sk" not in recovered
    assert "token" not in recovered


def test_exp_is_now_plus_ttl(monkeypatch):
    monkeypatch.setattr(signing.time, "time", lambda: 1000.0)
    recovered = decode_envelope(sign_payload({"a": 1}, ttl=120, include_sk=False))
    assert recovered["exp"] == 1120


def test_make_sk_body_carries_domain_and_future_exp(monkeypatch):
    monkeypatch.setattr(signing.time, "time", lambda: 1000.0)
    sk = make_sk(domain="example.test", ttl=60)
    header, body, sig = sk.split(".")
    claims = json.loads(_b64url_decode(body))
    assert claims == {"domain": "example.test", "exp": 1060}
