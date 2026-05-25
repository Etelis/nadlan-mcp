"""Request signing for the nadlan.gov.il dynamic API (api.nadlan.gov.il).

The site protects its dynamic POST endpoints (``/deal-data``, ``/deal-info``,
``/contact-us``) with a home-grown scheme layered on top of Google reCAPTCHA
Enterprise. The scheme is fully client-side and therefore reproducible:

1. The request payload (a plain dict of query fields) is augmented with
   ``exp`` (unix expiry, now + 120s) and ``domain`` (the site hostname).
2. It is signed as an HS256 JWT using a secret hard-coded in the site bundle.
3. The resulting JWT string is *reversed* and wrapped as ``{"##": "<reversed>"}``.

A second short-lived JWT (``sk``) carrying only ``{domain, exp}`` is placed
*inside* the payload before signing (this one is not reversed).

The HMAC secret below is not a credential we hold privately - it ships in the
public JavaScript bundle served from www.nadlan.gov.il and is identical for
every visitor. It is reproduced here only to mirror what the browser does.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

# Hard-coded in the public site bundle (assets/index.*.js); same for all users.
HMAC_SECRET = b"90c3e620192348f1bd46fcd9138c3c68"

# The bundle sets token lifetime to `Tf = 120` seconds.
TOKEN_TTL_SECONDS = 120

# The signature is bound to this hostname via the `domain` claim.
DEFAULT_DOMAIN = "www.nadlan.gov.il"

_JWT_HEADER = b'{"alg":"HS256","typ":"JWT"}'


def _b64url(raw: bytes) -> bytes:
    """Base64url without padding, as used by JWT."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _sign_jwt(payload: dict, secret: bytes = HMAC_SECRET) -> str:
    """Produce a compact HS256 JWT for ``payload``."""
    header = _b64url(_JWT_HEADER)
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = header + b"." + body
    signature = _b64url(hmac.new(secret, signing_input, hashlib.sha256).digest())
    return (signing_input + b"." + signature).decode("ascii")


def make_sk(domain: str = DEFAULT_DOMAIN, ttl: int = TOKEN_TTL_SECONDS) -> str:
    """Build the inner ``sk`` token: an HS256 JWT of ``{domain, exp}`` (not reversed)."""
    return _sign_jwt({"domain": domain, "exp": int(time.time()) + ttl})


def sign_payload(
    payload: dict,
    *,
    domain: str = DEFAULT_DOMAIN,
    ttl: int = TOKEN_TTL_SECONDS,
    recaptcha_token: str | None = None,
    include_sk: bool = True,
) -> dict:
    """Wrap ``payload`` into the ``{"##": <reversed-jwt>}`` envelope the API expects.

    Args:
        payload: The business fields (e.g. ``base_id``, ``base_name``, ``fetch_number``).
        domain: Hostname bound into the signature; must match an allowed origin.
        ttl: Token lifetime in seconds.
        recaptcha_token: Server-verified reCAPTCHA token (from ``/token-verify``).
            Required by ``/deal-data`` in normal operation; see README.
        include_sk: Whether to embed the inner ``sk`` token (the site always does).

    Returns:
        A dict ready to be ``json.dumps``'d as the POST body.
    """
    now = int(time.time())
    body = dict(payload)
    if include_sk:
        body.setdefault("sk", make_sk(domain, ttl))
    if recaptcha_token is not None:
        body["token"] = recaptcha_token
    body["exp"] = now + ttl
    body["domain"] = domain

    jwt = _sign_jwt(body)
    reversed_jwt = jwt[::-1]
    return {"##": reversed_jwt}


def decode_envelope(envelope: dict) -> dict:
    """Inverse of :func:`sign_payload` - recover the payload from a ``{"##": ...}`` body.

    Useful for debugging captured requests. Does not verify the signature.
    """
    reversed_jwt = envelope["##"]
    jwt = reversed_jwt[::-1]
    body_b64 = jwt.split(".")[1]
    padding = "=" * (-len(body_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(body_b64 + padding))
