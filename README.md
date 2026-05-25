# nadlan-mcp

Give your AI agent live access to **Israeli real-estate data** from the government
site [nadlan.gov.il](https://www.nadlan.gov.il/) (Gov נדל״ן) — median prices, rent
levels, price trends and rental yields for any city, neighborhood or street.

`nadlan-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server.
Connect it once and your agent (Claude Code, Claude Desktop, Cursor, or any MCP client)
can answer questions like:

> *"What's the median price of a 4-room apartment in Tel Aviv, and the rental yield?"*
> *"Find Rothschild St in Tel Aviv and compare price trends of nearby neighborhoods."*
> *"Which neighborhoods in Givat Shmuel had rising prices last year?"*

---

## Install & connect

```bash
pip install nadlan-mcp
```

**Claude Code**

```bash
claude mcp add nadlan -- nadlan-mcp
```

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "nadlan": { "command": "nadlan-mcp" }
  }
}
```

**Any other MCP client** — run the `nadlan-mcp` command as a stdio server. If the
client needs an absolute path, use the one from `which nadlan-mcp`, or
`python -m nadlan.mcp_server`.

That's it — restart/reload your client and the tools below appear. Prices are in ILS (₪);
queries can be in Hebrew or English.

---

## What your agent can do

| Tool | What it answers |
|---|---|
| `search(query)` | Turn a free-text place/street name into ids (**start here**) |
| `get_settlement_overview(settlement_code)` | A city/town's median prices by room count, YoY change, rental yield, luxury score |
| `get_neighborhood_overview(uniq_id)` | The same headline figures for one neighborhood |
| `list_neighborhoods(settlement_code)` | All neighborhoods of a city |
| `list_streets(settlement_code, name_contains=)` | Streets of a city (filterable) |
| `list_property_types()` | Property-type codes (apartment, penthouse, …) |
| `get_transactions(base_name, base_id)` | Individual sales — **experimental, see below** |

Each tool accepts a `rent=true` option (where relevant) to switch from the sale market
to the rental market. Responses are compact summaries, not raw multi-megabyte dumps, so
they stay cheap on agent context.

A typical flow the agent follows on its own: `search("תל אביב")` → take the
`SETTLEMENT` id → `get_settlement_overview(5000)` → `list_neighborhoods(5000)` →
`get_neighborhood_overview(<id>)`.

---

## A note on individual transactions

The `get_transactions` tool is **experimental** and currently returns no rows. The
government's per-transaction endpoint is protected by reCAPTCHA and refuses automated
callers, so this package ships the tool wired-but-disabled (it returns an explanatory
note rather than failing). **Everything else works fully and needs no keys or auth** —
the trend and summary tools are the recommended way to analyze the market.

---

## Privacy & fair use

This connects to a public government website on your behalf and reads published data.
It is not affiliated with or endorsed by the Israeli government. Please be considerate —
the data is for personal and analytical use; don't hammer the service.

---

## For developers

`nadlan-mcp` is also a plain Python client and an optional REST API. The full endpoint
reference, the reverse-engineering write-up, library usage, and contribution/build notes
live in **[docs/internals.md](docs/internals.md)**.
