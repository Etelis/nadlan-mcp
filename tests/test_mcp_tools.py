"""Tests for the MCP tool surface.

Schema tests run offline. The `live` test hits the real API and is skipped
unless `RUN_LIVE=1` is set in the environment.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from nadlan.mcp_server import mcp

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


def test_all_tools_registered():
    assert set(_tools()) == EXPECTED_TOOLS


def test_tools_are_read_only():
    for tool in _tools().values():
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True


def test_base_name_is_an_enum():
    schema = _tools()["get_transactions"].inputSchema
    assert schema["properties"]["base_name"]["enum"] == [
        "streetCode",
        "neighborhoodId",
        "settlmentID",
        "addressId",
        "kParcelName",
    ]


def test_parameters_have_descriptions():
    schema = _tools()["get_settlement_overview"].inputSchema
    assert schema["properties"]["settlement_code"]["description"]


@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 for live API test")
def test_live_settlement_overview():
    result = asyncio.run(mcp.call_tool("get_settlement_overview", {"settlement_code": 5000}))
    text = result[0].text if isinstance(result, list) else result[0][0].text
    assert "תל אביב" in text
