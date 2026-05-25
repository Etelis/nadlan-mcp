"""Tests for the MCP tool surface.

Schema/logic tests run offline. The `live` test hits the real API and is skipped
unless `RUN_LIVE=1` is set.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from nadlan import mcp_server
from nadlan.client import BASE_NAME_BY_TYPE
from nadlan.mcp_server import (
    ToolError,
    _to_float,
    _trends_summary,
    get_transactions,
    list_streets,
    mcp,
    safe,
)

EXPECTED_TOOLS = {
    "search",
    "get_settlement_overview",
    "get_neighborhood_overview",
    "list_neighborhoods",
    "list_streets",
    "list_property_types",
    "get_transactions",
}


def _tools():
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


# --- schema ------------------------------------------------------------------

def test_all_tools_registered():
    assert set(_tools()) == EXPECTED_TOOLS


def test_tools_are_read_only():
    for tool in _tools().values():
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True


def test_base_name_enum_matches_client_mapping():
    """The MCP Literal must not drift from the client's BASE_NAME_BY_TYPE."""
    enum = set(_tools()["get_transactions"].inputSchema["properties"]["base_name"]["enum"])
    assert enum == set(BASE_NAME_BY_TYPE.values())


def test_parameters_have_descriptions():
    for tool in _tools().values():
        for name, schema in tool.inputSchema.get("properties", {}).items():
            assert schema.get("description"), f"{tool.name}.{name} missing description"


# --- _trends_summary / _to_float --------------------------------------------

def test_trends_summary_projects_and_coerces():
    blob = {
        "rooms": [{"numRooms": 3, "hasDeals": 1, "summary": {"lastYearAvgPrice": 100, "priceDifferencePercentage": "-1.5"}}],
        "indexes": {"priceIncreases": "2.0", "yield": 2.7, "luxury": 9},
    }
    out = _trends_summary(blob)
    assert out["median_price_by_rooms"][0] == {
        "rooms": 3, "last_year_median_ils": 100, "yoy_change_pct": -1.5, "has_deals": True
    }
    assert out["price_change_pct_last_year"] == 2.0
    assert out["median_rental_yield_pct"] == 2.7


def test_trends_summary_handles_empty():
    out = _trends_summary({})
    assert out["median_price_by_rooms"] == []
    assert out["price_change_pct_last_year"] is None
    assert out["luxury_score_0_10"] is None


def test_to_float_handles_bad_input():
    assert _to_float("3.1") == 3.1
    assert _to_float(None) is None
    assert _to_float("n/a") is None


# --- safe decorator (error mapping, no leakage) ------------------------------

def _raise(exc):
    @safe
    def fn():
        raise exc
    return fn


def test_safe_maps_404_to_actionable_message():
    req = httpx.Request("GET", "https://data.nadlan.gov.il/secret.json")
    exc = httpx.HTTPStatusError("403", request=req, response=httpx.Response(403, request=req))
    with pytest.raises(ToolError) as ei:
        _raise(exc)()
    assert "search" in str(ei.value)
    assert "data.nadlan.gov.il" not in str(ei.value)  # no URL leak
    assert ei.value.__cause__ is None  # raised `from None`


def test_safe_maps_other_status_and_network_error():
    req = httpx.Request("GET", "https://x")
    exc = httpx.HTTPStatusError("500", request=req, response=httpx.Response(500, request=req))
    with pytest.raises(ToolError) as ei:
        _raise(exc)()
    assert "500" in str(ei.value)

    with pytest.raises(ToolError) as ei:
        _raise(httpx.ConnectError("boom"))()
    assert "network" in str(ei.value)


# --- list_streets filter (regression for numeric/None titles) ---------------

def test_list_streets_filter_survives_numeric_and_none_names(monkeypatch):
    monkeypatch.setattr(
        mcp_server._nadlan, "settlement_summary",
        lambda code: {"otherSettlmentStreets": [
            {"id": 1, "title": "רוטשילד"},
            {"id": 2, "title": 4843},   # numeric street name
            {"id": 3, "title": None},
        ]},
    )
    out = list_streets(5000, name_contains="רוטשילד")
    assert out["total"] == 1
    assert out["streets"][0]["id"] == 1


# --- get_transactions note ---------------------------------------------------

def test_get_transactions_sets_note_on_empty_405(monkeypatch):
    monkeypatch.setattr(
        mcp_server._nadlan, "deal_data",
        lambda *a, **k: {"statusCode": 405, "data": {"total_rows": 0, "items": []}},
    )
    out = get_transactions("streetCode", "1")
    assert out["note"] and "reCAPTCHA" in out["note"]


def test_get_transactions_no_note_when_items_present(monkeypatch):
    monkeypatch.setattr(
        mcp_server._nadlan, "deal_data",
        lambda *a, **k: {"statusCode": 200, "data": {"total_rows": 1, "items": [{"id": 1}]}},
    )
    out = get_transactions("streetCode", "1")
    assert out["note"] is None
    assert out["items"] == [{"id": 1}]


# --- live --------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 for live API test")
def test_live_settlement_overview():
    result = asyncio.run(mcp.call_tool("get_settlement_overview", {"settlement_code": 5000}))
    text = result[0].text if isinstance(result, list) else result[0][0].text
    assert "תל אביב" in text
