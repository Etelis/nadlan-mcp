"""A typed client for the (reverse-engineered) nadlan.gov.il data sources.

Two distinct backends sit behind the site:

* **Static data** on ``https://data.nadlan.gov.il/api`` - plain JSON files on
  S3/CloudFront, no authentication. This is where almost everything useful
  lives: per-settlement and per-neighborhood summaries, price trends, rental
  yields, street lists and several lookup indexes.

* **Dynamic API** on ``https://api.nadlan.gov.il`` - AWS API Gateway endpoints
  that require the signed envelope from :mod:`nadlan.signing` plus a
  reCAPTCHA token. The transaction-listing endpoint (``/deal-data``) lives here.

Address/name -> id resolution piggybacks on the public **govmap** search service
(``https://es.govmap.gov.il/TldSearch``), exactly as the site does.

See README.md for the full endpoint catalogue and field notes.
"""

from __future__ import annotations

import base64
import gzip
import json
import ssl
from dataclasses import dataclass
from typing import Any

import httpx

from .signing import DEFAULT_DOMAIN, sign_payload

DATA_BASE = "https://data.nadlan.gov.il/api"
API_BASE = "https://api.nadlan.gov.il"
GOVMAP_SEARCH = "https://es.govmap.gov.il/TldSearch/api"

# Maps a search-result "type" / site view to the ``base_name`` the dynamic API
# expects. Note the (sic) spelling of ``settlmentID`` - that is what the server
# accepts. ``setlCode`` is rejected as invalid.
BASE_NAME_BY_TYPE = {
    "STREET": "streetCode",
    "NEIGHBORHOOD": "neighborhoodId",
    "SETTLEMENT": "settlmentID",
    "ADDRESS": "addressId",
    "PARCEL_ALL": "kParcelName",
}

def _relaxed_ssl_context() -> ssl.SSLContext:
    """An SSL context that tolerates the older cipher suite on es.govmap.gov.il.

    Python's default security level rejects that host's handshake; lowering it
    to SECLEVEL=1 (still refusing genuinely broken crypto) restores parity with
    curl/browsers.
    """
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    return ctx


_BROWSER_HEADERS = {
    "Origin": "https://www.nadlan.gov.il",
    "Referer": "https://www.nadlan.gov.il/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


@dataclass
class SearchResult:
    """A single govmap autocomplete hit, normalised for our use."""

    type: str  # e.g. "STREET", "SETTLEMENT", "NEIGHBORHOOD"
    id: str  # the base_id to feed the dynamic API ("Key")
    label: str  # human-readable Hebrew label ("Value")

    @property
    def base_name(self) -> str | None:
        """The ``base_name`` to use for :meth:`NadlanClient.deal_data`, if known."""
        return BASE_NAME_BY_TYPE.get(self.type)


class DealDataUnavailable(RuntimeError):
    """Raised when /deal-data returns its empty 405 envelope.

    The endpoint is gated by reCAPTCHA Enterprise and returns ``statusCode: 405``
    with zero items for programmatic callers that lack a valid token. See README.md.
    """


class NadlanClient:
    def __init__(
        self,
        *,
        domain: str = DEFAULT_DOMAIN,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.domain = domain
        self._client = client or httpx.Client(timeout=timeout, headers=_BROWSER_HEADERS)
        # Dedicated client for govmap search, which needs a relaxed SSL context.
        self._search_client = httpx.Client(
            timeout=timeout, headers=_BROWSER_HEADERS, verify=_relaxed_ssl_context()
        )

    # ------------------------------------------------------------------ #
    # Search / id resolution (public govmap service, no auth)
    # ------------------------------------------------------------------ #
    def search(self, query: str) -> list[SearchResult]:
        """Autocomplete a free-text address/street/settlement query into typed ids.

        Mirrors the site's search box. Returns the ``Key`` values that the
        dynamic API consumes as ``base_id`` (e.g. ``"50001103"`` for a street).
        """
        resp = self._search_client.get(
            f"{GOVMAP_SEARCH}/AutoComplete",
            params={"query": query, "ids": "276267023", "gid": "govmap"},
        )
        resp.raise_for_status()
        data = resp.json()
        results: list[SearchResult] = []
        for type_name, hits in (data.get("res") or {}).items():
            for hit in hits:
                results.append(
                    SearchResult(
                        type=type_name,
                        id=str(hit.get("Key", "")),
                        label=hit.get("Value", ""),
                    )
                )
        return results

    # ------------------------------------------------------------------ #
    # Static data (no auth) - the bulk of what is actually retrievable today
    # ------------------------------------------------------------------ #
    def _get_json(self, url: str) -> Any:
        resp = self._client.get(url)
        resp.raise_for_status()
        # Several files are served with a UTF-8 BOM.
        return json.loads(resp.content.decode("utf-8-sig"))

    def settlement_summary(self, settlement_code: int | str, *, rent: bool = False) -> dict:
        """Per-settlement page: name, coordinates, neighborhoods, streets, price trends.

        Set ``rent=True`` for the rental-market variant.
        """
        kind = "rent" if rent else "buy"
        return self._get_json(f"{DATA_BASE}/pages/settlement/{kind}/{settlement_code}.json")

    def neighborhood_summary(self, neighborhood_id: int | str, *, rent: bool = False) -> dict:
        """Per-neighborhood page (keyed by the legacy ``UNIQ_ID``, e.g. 65210724).

        Use :meth:`settlement_summary` -> ``otherNeighborhoods`` to discover ids.
        """
        kind = "rent" if rent else "buy"
        return self._get_json(f"{DATA_BASE}/pages/neighborhood/{kind}/{neighborhood_id}.json")

    def settlement_details(self, settlement_code: int | str) -> dict:
        """Large ``additional_info`` blob for a settlement (street geometry, etc.)."""
        return self._get_json(f"{DATA_BASE}/additional_info/settlements/{settlement_code}.json")

    def neighborhood_details(self, neighborhood_id: int | str) -> dict:
        """``additional_info`` blob for a neighborhood."""
        return self._get_json(f"{DATA_BASE}/additional_info/neighborhoods/{neighborhood_id}.json")

    def neighborhood_compare(self, neighborhood_id: int | str) -> dict:
        """Cross-neighborhood comparison figures."""
        return self._get_json(f"{DATA_BASE}/compare/neighborhood/{neighborhood_id}.json")

    # ---- lookup indexes -------------------------------------------------- #
    def settlement_types(self) -> dict:
        """``{settlement_code: {SETL_NAME, TYPE, POPULATION, GLOBAL_TYPE}}``."""
        return self._get_json(f"{DATA_BASE}/index/setl_types.json")

    def neighborhoods_index(self) -> dict:
        """``{new_id: {UNIQ_ID_OLD}}`` - maps new neighborhood ids to legacy ids."""
        return self._get_json(f"{DATA_BASE}/index/neigh.json")

    def deal_natures(self) -> list[dict]:
        """Property-type codes: ``{DealNature, DealNatureDescription, NewDealNatureDescription}``."""
        return self._get_json(f"{DATA_BASE}/index/dealNatureIndex.json")

    def parcel_index(self) -> dict:
        """``{parcel_id: [polygon_id, neighborhood_id, settlement_code]}`` (~7 MB)."""
        return self._get_json(f"{DATA_BASE}/index/PolyNeighSett.json")

    # ------------------------------------------------------------------ #
    # Dynamic API (signed) - transaction listings
    # ------------------------------------------------------------------ #
    def deal_data(
        self,
        base_name: str,
        base_id: int | str,
        *,
        fetch_number: int = 1,
        type_order: str = "dealDate_down",
        room_num: str | None = None,
        deal_nature: str | None = None,
        deal_date: str | None = None,
        recaptcha_token: str | None = None,
        raise_on_empty: bool = False,
    ) -> dict:
        """Call ``POST /deal-data`` for a paged list of transactions.

        ``base_name``/``base_id`` come from :meth:`search` (see
        :attr:`SearchResult.base_name`). ``base_id`` is sent as a string.

        ``recaptcha_token`` is the server-verified token from ``/token-verify``.
        The endpoint is gated by reCAPTCHA Enterprise and rejects programmatic
        callers, so without a valid token it returns an empty ``statusCode: 405``
        envelope. The signing/transport is correct regardless.

        Returns the decoded ``{"statusCode", "data": {"total_rows", "items", ...}}``.
        """
        payload: dict[str, Any] = {
            "base_id": str(base_id),
            "base_name": base_name,
            "fetch_number": fetch_number,
            "type_order": type_order,
        }
        if room_num:
            payload["room_num"] = room_num
        if deal_nature:
            payload["deal_nature"] = deal_nature
        if deal_date:
            payload["deal_date"] = deal_date

        envelope = sign_payload(payload, domain=self.domain, recaptcha_token=recaptcha_token)
        resp = self._client.post(
            f"{API_BASE}/deal-data",
            content=json.dumps(envelope),
            headers={"Content-Type": "text/plain"},
        )
        decoded = _decode_api_body(resp.content)
        if raise_on_empty and decoded.get("statusCode") == 405:
            raise DealDataUnavailable(
                "deal-data returned an empty 405 envelope (currently affects all callers)."
            )
        return decoded

    def all_deals(self, base_name: str, base_id: int | str, **kwargs: Any):
        """Generator over every transaction, walking ``fetch_number`` pages.

        Stops when ``fetch_number`` exceeds ``data.total_page``.
        """
        page = 1
        while True:
            result = self.deal_data(base_name, base_id, fetch_number=page, **kwargs)
            data = result.get("data") or {}
            items = data.get("items") or []
            yield from items
            total_pages = data.get("total_page") or 0
            if page >= total_pages or not items:
                break
            page += 1

    def close(self) -> None:
        self._client.close()
        self._search_client.close()

    def __enter__(self) -> "NadlanClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _decode_api_body(raw: bytes) -> dict:
    """Decode an api.nadlan.gov.il response.

    Bodies are base64-encoded gzip (API Gateway binary passthrough). Some error
    responses are plain JSON; handle both.
    """
    try:
        return json.loads(gzip.decompress(base64.b64decode(raw)).decode("utf-8"))
    except Exception:
        return json.loads(raw.decode("utf-8"))
