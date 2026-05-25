"""MCP server exposing nadlan.gov.il (Israeli real-estate) data to agents.

Run over stdio (the usual MCP transport):

    pip install nadlan-mcp
    nadlan-mcp

Register it with an MCP client (e.g. Claude Code / Desktop) - see README.md.

Design notes for tool authors: the upstream JSON blobs are huge (a single city
summary embeds thousands of streets and 5-year price series). These tools return
*compact* projections so agents don't drown in tokens; raw access is still
available through the Python client in `nadlan/` if needed.
"""

from __future__ import annotations

import functools
from typing import Annotated, Any, Callable, Literal

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .client import NadlanClient

mcp = FastMCP(
    "nadlan",
    instructions=(
        "Query Israeli government real-estate data (nadlan.gov.il): resolve "
        "place/street names to ids, fetch median-price and rent trends per "
        "settlement or neighborhood, list neighborhoods/streets, and look up "
        "property-type codes. Start with `search` to turn a free-text query "
        "into ids, then pass those ids to the other tools. Prices are in ILS (₪)."
    ),
)

_nadlan = NadlanClient()


def _readonly(title: str) -> ToolAnnotations:
    """All tools here are read-only and hit a live, changing external API."""
    return ToolAnnotations(title=title, readOnlyHint=True, openWorldHint=True)


def safe(fn: Callable) -> Callable:
    """Map upstream HTTP/network failures to clean, agent-actionable ToolErrors.

    Avoids leaking internal URLs or stack traces to the model.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (403, 404):
                raise ToolError(
                    f"{fn.__name__}: no data for the given id "
                    "(it may be wrong or unavailable). Use `search` to find a valid id."
                ) from None
            raise ToolError(f"{fn.__name__}: upstream returned HTTP {code}.") from None
        except httpx.RequestError:
            raise ToolError(
                f"{fn.__name__}: could not reach nadlan.gov.il (network error)."
            ) from None

    return wrapper


def _trends_summary(trends: dict) -> dict:
    """Project the verbose `trends` blob down to the headline figures."""
    idx = trends.get("indexes") or {}
    rooms = []
    for room in trends.get("rooms") or []:
        summary = room.get("summary") or {}
        rooms.append(
            {
                "rooms": room.get("numRooms"),
                "last_year_median_ils": summary.get("lastYearAvgPrice"),
                "yoy_change_pct": _to_float(summary.get("priceDifferencePercentage")),
                "has_deals": bool(room.get("hasDeals")),
            }
        )
    return {
        "median_price_by_rooms": rooms,
        "price_change_pct_last_year": _to_float(idx.get("priceIncreases")),
        "median_rental_yield_pct": idx.get("yield"),
        "luxury_score_0_10": idx.get("luxury"),
    }


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@mcp.tool(annotations=_readonly("Search places"))
@safe
def search(
    query: Annotated[
        str, Field(description="Free-text Hebrew query, e.g. a street, city or address.")
    ],
) -> list[dict]:
    """Resolve a free-text Hebrew query (street / settlement / address) to typed ids.

    This is the entry point: most other tools need an id from here. Returns a list
    of hits, each with `type` (STREET / SETTLEMENT / NEIGHBORHOOD / ADDRESS), `id`
    (use as the id argument elsewhere), `label`, and `base_name` (for `get_transactions`).

    Example: search("רוטשילד תל אביב") -> [{type:"STREET", id:"50001103", ...}].
    """
    return [
        {"type": r.type, "id": r.id, "label": r.label, "base_name": r.base_name}
        for r in _nadlan.search(query)
    ]


@mcp.tool(annotations=_readonly("Settlement overview"))
@safe
def get_settlement_overview(
    settlement_code: Annotated[
        int, Field(description="Numeric settlement code, e.g. 5000 for Tel Aviv-Yafo.")
    ],
    rent: Annotated[
        bool, Field(description="True for the rental market, False for sales.")
    ] = False,
) -> dict:
    """Overview of a settlement (city/town): name, counts, and headline price trends.

    `settlement_code` is the numeric code (e.g. 5000 = Tel Aviv-Yafo), obtained from a
    `search` hit of type SETTLEMENT. Set `rent=True` for the rental market. Returns
    compact trends (median price by room count, YoY change, rental yield, luxury score)
    plus neighborhood/street counts - not the full lists. Use `list_neighborhoods` /
    `list_streets` for those.
    """
    s = _nadlan.settlement_summary(settlement_code, rent=rent)
    return {
        "settlement_code": s.get("settlementID"),
        "name": s.get("settlementName"),
        "neighborhood_count": len(s.get("otherNeighborhoods") or []),
        "street_count": len(s.get("otherSettlmentStreets") or []),
        "market": "rent" if rent else "buy",
        "trends": _trends_summary(s.get("trends") or {}),
    }


@mcp.tool(annotations=_readonly("Neighborhood overview"))
@safe
def get_neighborhood_overview(
    uniq_id: Annotated[
        int, Field(description="Legacy neighborhood id, e.g. 65210724 (from list_neighborhoods).")
    ],
    rent: Annotated[
        bool, Field(description="True for the rental market, False for sales.")
    ] = False,
) -> dict:
    """Overview of a single neighborhood: name, parent settlement, headline trends.

    `uniq_id` is the legacy neighborhood id - get it from `list_neighborhoods` or from
    a SETTLEMENT search. Set `rent=True` for rentals.
    """
    n = _nadlan.neighborhood_summary(uniq_id, rent=rent)
    return {
        "neighborhood_id": n.get("neighborhoodId"),
        "name": n.get("neighborhoodName"),
        "settlement_code": n.get("settlementID"),
        "settlement_name": n.get("settlementName"),
        "market": "rent" if rent else "buy",
        "trends": _trends_summary(n.get("trends") or {}),
    }


@mcp.tool(annotations=_readonly("List neighborhoods"))
@safe
def list_neighborhoods(
    settlement_code: Annotated[
        int, Field(description="Numeric settlement code, e.g. 5000 for Tel Aviv-Yafo.")
    ],
) -> list[dict]:
    """List the neighborhoods of a settlement as `{id, name}`.

    The `id` is the legacy neighborhood id to pass to `get_neighborhood_overview`.
    """
    s = _nadlan.settlement_summary(settlement_code)
    return [
        {"id": n.get("id"), "name": n.get("title")}
        for n in (s.get("otherNeighborhoods") or [])
    ]


@mcp.tool(annotations=_readonly("List streets"))
@safe
def list_streets(
    settlement_code: Annotated[
        int, Field(description="Numeric settlement code, e.g. 5000 for Tel Aviv-Yafo.")
    ],
    name_contains: Annotated[
        str | None, Field(description="Optional Hebrew substring to filter street names.")
    ] = None,
    limit: Annotated[
        int, Field(description="Max streets to return.", ge=1, le=500)
    ] = 100,
) -> dict:
    """List streets of a settlement as `{id, name}` (optionally filtered).

    A large city has thousands of streets, so pass `name_contains` (Hebrew substring)
    to filter and/or rely on `limit` (default 100). Returns `{total, returned, streets}`.
    """
    s = _nadlan.settlement_summary(settlement_code)
    streets = [
        {"id": st.get("id"), "name": st.get("title")}
        for st in (s.get("otherSettlmentStreets") or [])
    ]
    if name_contains:
        streets = [st for st in streets if name_contains in str(st["name"] or "")]
    total = len(streets)
    return {"total": total, "returned": min(total, limit), "streets": streets[:limit]}


@mcp.tool(annotations=_readonly("List property types"))
@safe
def list_property_types() -> list[dict]:
    """List property-type ("deal nature") codes used for filtering transactions.

    Returns `{code, description, category}` (e.g. 101 = דירה בבית קומות / apartment).
    Use a `code` as the `deal_nature` filter in `get_transactions`.
    """
    return [
        {
            "code": d.get("DealNature"),
            "description": d.get("DealNatureDescription"),
            "category": d.get("NewDealNatureDescription"),
        }
        for d in _nadlan.deal_natures()
    ]


@mcp.tool(annotations=_readonly("Get transactions"))
@safe
def get_transactions(
    base_name: Annotated[
        Literal["streetCode", "neighborhoodId", "settlmentID", "addressId", "kParcelName"],
        Field(description="Entity kind. Use the `base_name` from the matching `search` hit."),
    ],
    base_id: Annotated[
        str, Field(description="The id of that entity (the `id` from the `search` hit).")
    ],
    fetch_number: Annotated[
        int, Field(description="1-based page number.", ge=1)
    ] = 1,
    room_num: Annotated[
        str | None, Field(description='Optional room-count filter, e.g. "3,4".')
    ] = None,
    deal_nature: Annotated[
        str | None, Field(description="Optional property-type code from list_property_types.")
    ] = None,
) -> dict:
    """Fetch a page of individual sale transactions for a street/neighborhood/settlement.

    `base_name` and `base_id` come from `search` (use the hit's `base_name` and `id`).
    `fetch_number` is the 1-based page.

    EXPERIMENTAL: the upstream transaction endpoint is gated by reCAPTCHA Enterprise
    and rejects programmatic callers, so this currently returns an empty result with
    an explanatory `note`. The request signing/transport is correct and would return
    data if a valid token were available. For market analysis use the trend tools
    (get_settlement_overview / get_neighborhood_overview), which work fully.
    """
    result = _nadlan.deal_data(
        base_name,
        base_id,
        fetch_number=fetch_number,
        room_num=room_num,
        deal_nature=deal_nature,
    )
    data = result.get("data") or {}
    items = data.get("items") or []
    note = None
    if result.get("statusCode") == 405 and not items:
        note = (
            "The transaction endpoint is gated by reCAPTCHA Enterprise and returned "
            "an empty result for this programmatic call. No transactions available. "
            "Use the trend tools for median prices and rental yields."
        )
    return {
        "status_code": result.get("statusCode"),
        "total_rows": data.get("total_rows"),
        "total_pages": data.get("total_page"),
        "page": fetch_number,
        "items": items,
        "note": note,
    }


def main() -> None:
    """Console entry point (``nadlan-mcp``): serve the tools over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
