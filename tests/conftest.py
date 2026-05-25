"""Shared test fixtures: an offline NadlanClient backed by httpx.MockTransport."""

from __future__ import annotations

import base64
import gzip
import json
from collections.abc import Callable

import httpx
import pytest

from nadlan.client import NadlanClient


def api_body(obj: dict) -> bytes:
    """Encode ``obj`` the way api.nadlan.gov.il does: base64-wrapped gzip."""
    return base64.b64encode(gzip.compress(json.dumps(obj).encode("utf-8")))


@pytest.fixture
def make_client() -> Callable[[Callable[[httpx.Request], httpx.Response]], NadlanClient]:
    """Return a factory that builds a NadlanClient driven by a request handler.

    The handler receives an ``httpx.Request`` and returns an ``httpx.Response``;
    it backs both the data client and the govmap search client.
    """

    def factory(handler: Callable[[httpx.Request], httpx.Response]) -> NadlanClient:
        transport = httpx.MockTransport(handler)
        client = NadlanClient(client=httpx.Client(transport=transport))
        client._search_client = httpx.Client(transport=transport)
        return client

    return factory
