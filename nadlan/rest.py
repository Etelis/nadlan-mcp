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

from typing import Any

from fastapi import FastAPI, HTTPException, Query

from .client import BASE_NAME_BY_TYPE, NadlanClient

app = FastAPI(
    title="Nadlan API wrapper",
    description="Unofficial REST wrapper over nadlan.gov.il public data sources.",
    version="0.1.0",
)

nadlan = NadlanClient()


@app.get("/search")
def search(q: str = Query(..., description="Free-text address / street / settlement")) -> list[dict]:
    """Resolve a query to typed ids via the public govmap autocomplete."""
    return [
        {"type": r.type, "id": r.id, "label": r.label, "base_name": r.base_name}
        for r in nadlan.search(q)
    ]


@app.get("/settlements/{code}")
def settlement(code: str, rent: bool = False) -> dict:
    """Settlement summary: neighborhoods, streets, price/rent trends."""
    try:
        return nadlan.settlement_summary(code, rent=rent)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/settlements/{code}/details")
def settlement_details(code: str) -> dict:
    """Large additional_info blob (street geometry, etc.)."""
    try:
        return nadlan.settlement_details(code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/neighborhoods/{uniq_id}")
def neighborhood(uniq_id: str, rent: bool = False) -> dict:
    """Neighborhood summary (keyed by legacy UNIQ_ID, e.g. 65210724)."""
    try:
        return nadlan.neighborhood_summary(uniq_id, rent=rent)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/neighborhoods/{uniq_id}/compare")
def neighborhood_compare(uniq_id: str) -> dict:
    try:
        return nadlan.neighborhood_compare(uniq_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/indexes/settlement-types")
def settlement_types() -> dict:
    return nadlan.settlement_types()


@app.get("/indexes/deal-natures")
def deal_natures() -> list[dict]:
    return nadlan.deal_natures()


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
    return nadlan.deal_data(
        base_name,
        base_id,
        fetch_number=fetch_number,
        room_num=room_num,
        deal_nature=deal_nature,
        deal_date=deal_date,
    )


@app.on_event("shutdown")
def _shutdown() -> None:
    nadlan.close()
