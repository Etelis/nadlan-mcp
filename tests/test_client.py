"""Offline tests for nadlan.client: response decoding, parsing, transport."""

from __future__ import annotations

import json

import httpx
import pytest

from nadlan.client import SearchResult, _decode_api_body
from nadlan.signing import decode_envelope
from tests.conftest import api_body


# --- _decode_api_body --------------------------------------------------------

def test_decode_api_body_gzip_b64_roundtrip():
    obj = {"statusCode": 200, "data": {"items": [1, 2, 3]}}
    assert _decode_api_body(api_body(obj)) == obj


def test_decode_api_body_plain_json_fallback():
    # Some error responses are plain JSON, not base64-gzip.
    assert _decode_api_body(b'{"statusCode": 405}') == {"statusCode": 405}


def test_decode_api_body_invalid_raises():
    with pytest.raises(Exception):
        _decode_api_body(b"\x00 not json and not gzip")


# --- search parsing ----------------------------------------------------------

def test_search_parses_and_maps_results(make_client):
    payload = {
        "res": {
            "STREET": [{"Key": 50001103, "Value": "רוטשילד"}],
            "SETTLEMENT": [{"Key": 5000, "Value": "תל אביב"}],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "AutoComplete" in request.url.path
        return httpx.Response(200, json=payload)

    results = {r.type: r for r in make_client(handler).search("x")}
    assert results["STREET"].id == "50001103"  # numeric Key coerced to str
    assert results["STREET"].base_name == "streetCode"
    assert results["SETTLEMENT"].base_name == "settlmentID"  # (sic)


def test_searchresult_base_name_unknown_type_is_none():
    assert SearchResult(type="POI_MID_POINT", id="1", label="x").base_name is None


# --- deal_data signing + decoding -------------------------------------------

def test_deal_data_signs_envelope_and_decodes_response(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, content=api_body({"statusCode": 200, "data": {"items": []}}))

    result = make_client(handler).deal_data("streetCode", 50001103, room_num="3")

    envelope = captured["body"]
    assert set(envelope) == {"##"}  # the {"##": reversed-jwt} envelope
    recovered = decode_envelope(envelope)
    assert recovered["base_name"] == "streetCode"
    assert recovered["base_id"] == "50001103"  # sent as string
    assert recovered["room_num"] == "3"
    assert result["statusCode"] == 200


def test_all_deals_paginates_then_stops(make_client):
    pages = {
        1: {"statusCode": 200, "data": {"total_page": 2, "items": [{"id": 1}]}},
        2: {"statusCode": 200, "data": {"total_page": 2, "items": [{"id": 2}]}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = decode_envelope(json.loads(request.content.decode("utf-8")))["fetch_number"]
        return httpx.Response(200, content=api_body(pages[page]))

    items = list(make_client(handler).all_deals("streetCode", "1"))
    assert [it["id"] for it in items] == [1, 2]
