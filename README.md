# nadlan-mcp — Israeli real-estate data for agents & code

An unofficial **MCP server**, Python client, and REST wrapper for the Israeli
government real-estate site **[nadlan.gov.il](https://www.nadlan.gov.il/)**
(Gov נדל״ן), plus full documentation of the endpoints behind it.

The public site is a Vue/React single-page app served as static files from S3/CloudFront.
All of its data comes from three backends, documented below. This repo wraps them.

```python
from nadlan import NadlanClient

with NadlanClient() as nadlan:
    hits = nadlan.search("רוטשילד תל אביב")          # -> [SearchResult(type='STREET', id='50001103', ...)]
    tlv  = nadlan.settlement_summary(5000)            # Tel Aviv-Yafo: trends, neighborhoods, streets
    nbhd = nadlan.neighborhood_summary(65210724)      # a neighborhood's trends
```

```bash
pip install nadlan-mcp            # core: Python client + MCP server
nadlan-mcp                        # run the MCP server (stdio) for AI agents

pip install "nadlan-mcp[rest]"    # optional REST wrapper
uvicorn nadlan.rest:app --reload  # REST API at http://127.0.0.1:8000/docs
```

---

## Architecture at a glance

| Backend | Base URL | Auth | What's there |
|---|---|---|---|
| **Static data** | `https://data.nadlan.gov.il/api` | none | Settlement/neighborhood summaries, price & rent trends, street lists, lookup indexes. **This is the bulk of the usable data.** |
| **Dynamic API** | `https://api.nadlan.gov.il` | signed envelope + reCAPTCHA | Transaction listings (`/deal-data`), deal detail (`/deal-info`), contact form, token verify. |
| **Search** | `https://es.govmap.gov.il/TldSearch` | none | Free-text → typed ids (street / settlement / neighborhood / address). Shared national GIS service. |

Runtime config (base URLs, reCAPTCHA site key, map tokens) is fetched by the SPA from
[`https://www.nadlan.gov.il/config.json`](https://www.nadlan.gov.il/config.json).

---

## 1. Static data — `https://data.nadlan.gov.il/api` (no auth)

Plain JSON files (some served with a UTF-8 BOM; bodies are gzip-on-the-wire by CloudFront).

### Summaries (the "page" files)

| Endpoint | Notes |
|---|---|
| `GET /pages/settlement/buy/{settlement_code}.json` | Per-settlement sale summary. Keys: `settlementName`, `x`, `y`, `otherNeighborhoods[]`, `otherSettlmentStreets[]`, `trends`. |
| `GET /pages/settlement/rent/{settlement_code}.json` | Rental variant. |
| `GET /pages/neighborhood/buy/{uniq_id}.json` | Per-neighborhood sale summary. **Keyed by the legacy `UNIQ_ID`** (e.g. `65210724`), not the new id. |
| `GET /pages/neighborhood/rent/{uniq_id}.json` | Rental variant. |

`trends.rooms[]` holds quarterly median price series per room count
(`numRooms` ∈ `3,4,5,'all'`), each with a 5-year `graphData[]` of
`{settlementPrice, countryPrice, year, month}` and a `summary`
(`lastYearAvgPrice`, `priceDifferencePercentage`). `trends.indexes` holds the
"luxury score", rental yield, etc.

### Detail / extras

| Endpoint | Notes |
|---|---|
| `GET /additional_info/settlements/{code}.json` | Large blob (~1.7 MB for TLV): street geometry & per-street stats. |
| `GET /additional_info/neighborhoods/{uniq_id}.json` | Neighborhood extras. |
| `GET /additional_info/bus/{...}.json` | Public-transport overlays. |
| `GET /compare/neighborhood/{uniq_id}.json` | Cross-neighborhood comparison figures. |

### Lookup indexes

| Endpoint | Shape |
|---|---|
| `GET /index/setl_types.json` | `{ "<code>": { SETL_NAME, TYPE, POPULATION, GLOBAL_TYPE } }` |
| `GET /index/neigh.json` | `{ "<new_id>": { UNIQ_ID_OLD } }` — maps new → legacy neighborhood ids |
| `GET /index/dealNatureIndex.json` | `[ { DealNature, DealNatureDescription, NewDealNatureDescription } ]` — property-type codes (101 = apartment, …) |
| `GET /index/PolyNeighSett.json` | `{ "<parcel_id>": [polygon_id, neighborhood_id, settlement_code] }` (~7 MB) |

> Note: `/api/deals/…` and `/api/rents/…` paths exist in config but return **403** (private).

---

## 2. Dynamic API — `https://api.nadlan.gov.il` (signed)

### The request envelope

Every dynamic POST body is a signed envelope, **not** raw JSON:

```
body = { "##": reverse( HS256_JWT( payload + {sk, exp, domain} ) ) }
Content-Type: text/plain
```

1. Build the `payload` (query fields, see below).
2. Add `sk` = an HS256 JWT of just `{domain, exp}` (this inner one is **not** reversed).
3. Add `exp` = `now + 120`, `domain` = `"www.nadlan.gov.il"`.
4. Sign the whole thing as an HS256 JWT, **reverse the string**, wrap as `{"##": ...}`.

The HMAC secret (`90c3e620192348f1bd46fcd9138c3c68`) is **hard-coded in the public
site bundle** and identical for every visitor, so the envelope is fully reproducible —
see [`nadlan/signing.py`](nadlan/signing.py). This is the site's tamper/expiry check,
not a private key.

**Responses** are base64-encoded gzip (API Gateway binary passthrough) wrapping
`{"statusCode", "data": {total_rows, total_fetch, total_page, items[]}}`.

### `POST /deal-data` — transaction listing

Payload fields:

| Field | Required | Example | Notes |
|---|---|---|---|
| `base_id` | ✔ | `"50001103"` | **string**. From search (`Key`). |
| `base_name` | ✔ | `"streetCode"` | entity type — see table below |
| `fetch_number` | ✔ | `1` | page number (1-based) |
| `type_order` | ✔ | `"dealDate_down"` | sort |
| `room_num` | | `"3,4"` | filter by room counts |
| `deal_nature` | | `"101"` | filter by property type |
| `deal_date` | | | date filter |
| `sk`, `exp`, `domain`, `token` | ✔ | | injected by the signer / reCAPTCHA |

`base_name` vocabulary (note the **`settlmentID`** misspelling — that is what the
server accepts; `setlCode` is rejected):

| Search type / site `view` | `base_name` | `base_id` example |
|---|---|---|
| street | `streetCode` | `50001103` (settlement+street) |
| neighborhood | `neighborhoodId` | |
| settlement | `settlmentID` *(sic)* | `5000` |
| address | `addressId` | |
| parcel (גוש/חלקה) | `kParcelName` | |

### `POST /deal-info` — single deal / parcel detail

Same envelope. Uses server-side id names: `setl_id`, `addr_id`, `polygon_id`, `parcel_id`.

### `POST /token-verify` — reCAPTCHA exchange

`{ "token": "<client reCAPTCHA Enterprise token>" }` → `{ "token": "<server token>" }`.
The server token is then placed in the `/deal-data` payload as `token`.

### ⚠️ Status of `/deal-data` (transactions)

`/deal-data` is gated by **reCAPTCHA Enterprise**. We verified that a headless browser
can mint a client reCAPTCHA token, but `/token-verify` rejects it (HTTP 400) — i.e. the
backend scores programmatic callers as bots and refuses to issue a usable token, so
`/deal-data` returns `statusCode: 405` with `total_rows: 0` for automated clients.

The signing and transport in this repo are byte-for-byte identical to the site's, so
`deal_data()` would return real rows given a valid token. This package therefore ships
`get_transactions` as **experimental** and does **not** bundle any reCAPTCHA-bypass code.
For analysis, use the trend endpoints, which work fully and need no auth.

---

## 3. Search — `https://es.govmap.gov.il/TldSearch` (no auth)

```
GET /api/AutoComplete?query=<text>&ids=276267023&gid=govmap
```

Returns `{ "res": { "STREET": [ {Key, Value, Rank}, … ], "SETTLEMENT": […] }, "order": […] }`.
`Key` is the `base_id` for the dynamic API; the dict key (`STREET`, …) maps to `base_name`.

> This host negotiates an older TLS suite that Python's default rejects; the client uses a
> relaxed `SECLEVEL=1` SSL context for it (see `nadlan/client.py`). `curl` is unaffected.

---

## MCP server — for AI agents

Exposes the data as [Model Context Protocol](https://modelcontextprotocol.io) tools so any
MCP-capable agent (Claude Code, Claude Desktop, etc.) can query Israeli real-estate data.
Runs over stdio via the `nadlan-mcp` command. Tools return **compact** projections (not the
multi-MB raw blobs) to keep agent token usage low.

| Tool | Purpose |
|---|---|
| `search(query)` | Free-text → typed ids (start here) |
| `get_settlement_overview(settlement_code, rent=)` | City/town name, counts, headline price/rent trends |
| `get_neighborhood_overview(uniq_id, rent=)` | Neighborhood trends |
| `list_neighborhoods(settlement_code)` | `{id, name}` per neighborhood |
| `list_streets(settlement_code, name_contains=, limit=)` | Streets (filterable) |
| `list_property_types()` | Property-type ("deal nature") codes |
| `get_transactions(base_name, base_id, …)` | Individual sales — **experimental** (see `/deal-data` status above) |

### Register with Claude Code

```bash
pip install nadlan-mcp
claude mcp add nadlan -- nadlan-mcp
```

### Register with Claude Desktop

Add to `claude_desktop_config.json` (use an absolute path to the `nadlan-mcp`
executable, or `python -m nadlan.mcp_server`):

```json
{
  "mcpServers": {
    "nadlan": { "command": "nadlan-mcp" }
  }
}
```

Then ask the agent things like *"What are 3-room median prices and rental yield in Tel Aviv?"*
or *"Find Rothschild St in Tel Aviv and list nearby neighborhoods."*

---

## REST wrapper (`nadlan.rest`) — optional

Install with `pip install "nadlan-mcp[rest]"`, run `uvicorn nadlan.rest:app`.

| Route | Description |
|---|---|
| `GET /search?q=` | govmap autocomplete → typed ids |
| `GET /settlements/{code}` (`?rent=`) | settlement summary + trends |
| `GET /settlements/{code}/details` | additional_info blob |
| `GET /neighborhoods/{uniq_id}` (`?rent=`) | neighborhood summary |
| `GET /neighborhoods/{uniq_id}/compare` | comparison figures |
| `GET /indexes/settlement-types` · `/indexes/deal-natures` | lookup indexes |
| `GET /deals?base_name=&base_id=&fetch_number=` | signed `/deal-data` (see outage note) |

---

## Files

```
nadlan/signing.py        # the {"##": reversed-JWT} envelope (HMAC, sk, exp, domain)
nadlan/client.py         # typed client: search, static data, indexes, deal-data
nadlan/mcp_server.py     # MCP server (stdio) exposing the data as agent tools
nadlan/rest.py           # FastAPI REST wrapper (optional [rest] extra)
examples/quickstart.py   # end-to-end demo
tests/                   # offline + live smoke tests
```

## Legal / usage

This wraps a public government site for personal/analytical use. Be polite: the dynamic
API is rate-limited and reCAPTCHA-gated. Prefer the static endpoints, cache aggressively,
and don't hammer it. Not affiliated with or endorsed by the Israeli government.
