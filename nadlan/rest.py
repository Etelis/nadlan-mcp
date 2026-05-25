"""A small REST wrapper exposing the nadlan.gov.il data as a clean JSON API.

Run::

    pip install "nadlan-mcp[rest]"
    uvicorn nadlan.rest:app --reload

Then e.g.::

    GET /search?q=רוטשילד תל אביב
    GET /settlements/5000
    GET /settlements/5000?rent=true
    GET /neighborhoods/65210724
    GET /indexes/deal-natures
    GET /deals?base_name=streetCode&base_id=50001103

Interactive docs at http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query

from .client import BASE_NAME_BY_TYPE, NadlanClient

nadlan = NadlanClient()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Close the shared HTTP client(s) when the app shuts down."""
    yield
    nadlan.close()


app = FastAPI(
    title="Nadlan API wrapper",
    description="Unofficial REST wrapper over nadlan.gov.il public data sources.",
    version="0.1.0",
    lifespan=lifespan,
)


def _fetch(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a client method, mapping upstream HTTP/network errors to clean HTTP codes."""
    try:
        return fn(*args, **kwargs)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # 403/404 from the static store means "no such id"; anything else is a gateway issue.
        raise HTTPException(status_code=404 if status in (403, 404) else 502) from None
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="upstream request failed") from None


@app.get("/search")
def search(q: str = Query(..., description="Free-text address / street / settlement")) -> list[dict]:
    """Resolve a query to typed ids via the public govmap autocomplete."""
    return [
        {"type": r.type, "id": r.id, "label": r.label, "base_name": r.base_name}
        for r in _fetch(nadlan.search, q)
    ]


@app.get("/settlements/{code}")
def settlement(code: str, rent: bool = False) -> dict:
    """Settlement summary: neighborhoods, streets, price/rent trends."""
    return _fetch(nadlan.settlement_summary, code, rent=rent)


@app.get("/settlements/{code}/details")
def settlement_details(code: str) -> dict:
    """Large additional_info blob (street geometry, etc.)."""
    return _fetch(nadlan.settlement_details, code)


@app.get("/neighborhoods/{uniq_id}")
def neighborhood(uniq_id: str, rent: bool = False) -> dict:
    """Neighborhood summary (keyed by legacy UNIQ_ID, e.g. 65210724)."""
    return _fetch(nadlan.neighborhood_summary, uniq_id, rent=rent)


@app.get("/neighborhoods/{uniq_id}/compare")
def neighborhood_compare(uniq_id: str) -> dict:
    """Cross-neighborhood comparison figures."""
    return _fetch(nadlan.neighborhood_compare, uniq_id)


@app.get("/indexes/settlement-types")
def settlement_types() -> dict:
    """Settlement-type lookup index: ``{code: {SETL_NAME, TYPE, POPULATION, ...}}``."""
    return _fetch(nadlan.settlement_types)


@app.get("/indexes/deal-natures")
def deal_natures() -> list[dict]:
    """Property-type ("deal nature") code index."""
    return _fetch(nadlan.deal_natures)


@app.get("/deals")
def deals(
    base_name: str = Query(..., description=f"One of: {sorted(set(BASE_NAME_BY_TYPE.values()))}"),
    base_id: str = Query(...),
    fetch_number: int = 1,
    room_num: str | None = None,
    deal_nature: str | None = None,
    deal_date: str | None = None,
) -> dict[str, Any]:
    """Transaction listing via the signed dynamic API.

    NOTE: api.nadlan.gov.il/deal-data is gated by reCAPTCHA Enterprise and rejects
    programmatic callers, returning an empty ``statusCode: 405`` envelope, so
    ``items`` is typically empty. The signing/transport here is correct and would
    return data given a valid reCAPTCHA token.
    """
    return _fetch(
        nadlan.deal_data,
        base_name,
        base_id,
        fetch_number=fetch_number,
        room_num=room_num,
        deal_nature=deal_nature,
        deal_date=deal_date,
    )
