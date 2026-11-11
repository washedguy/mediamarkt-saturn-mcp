# MediaMarkt & Saturn MCP

Search products, compare prices, find stores, and check pickup availability at MediaMarkt, MediaWorld, and Saturn storefronts. No account or API key required.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv sync --frozen
uv run mediamarkt-saturn-mcp --config
```

Copy the generated JSON into your MCP client's configuration and restart the client. Merge the entry into `mcpServers` if the section already exists. Run `--config` again if you move the project or recreate the environment.

<details>
<summary>Example configuration</summary>

Replace the path with the one printed by `--config`:

```json
{
  "mcpServers": {
    "mediamarkt-saturn": {
      "command": "/path/to/project/.venv/bin/python",
      "args": ["-m", "mediamarkt_mcp.server"]
    }
  }
}
```

</details>

## Tools

| Tool | What it does |
| --- | --- |
| `list_storefronts` | List supported countries, shop languages, currencies, and delivery filters. |
| `search_products` | Search by keyword, brand, price, and home delivery. Set `include_offers: true` to also fetch linked variants and marketplace offers. |
| `get_product` | Get product details, variants, and marketplace offers by ID or URL. |
| `find_stores` | Find stores by city, postal code, or name. |
| `check_pickup_availability` | Check product IDs at a selected store. |

Choose `mediamarkt` or `saturn` as `retailer` and set `country` and, optionally, `language`. Defaults are `mediamarkt`, `de`, and the country's default language. Use the same retailer and country for products and stores; IDs are country-specific. Italy uses MediaWorld under `retailer: mediamarkt`.

| Country | `country` | Shop languages |
| --- | --- | --- |
| Germany | `de` | `de` (MediaMarkt and Saturn) |
| Austria | `at` | `de` |
| Switzerland | `ch` | `de`, `fr`, `it` |
| Netherlands | `nl` | `nl` |
| Belgium | `be` | `nl`, `fr` |
| Spain | `es` | `es` |
| Italy | `it` | `it` |
| Poland | `pl` | `pl` |
| Hungary | `hu` | `hu` |
| Türkiye | `tr` | `tr` |

Prices use the storefront's local currency. `delivery_only` uses the shop's in-stock delivery filter and is not yet available for Spain, Italy, or Türkiye. For example:

> Find Nintendo Switch consoles at Saturn under €500, then check pickup at a store in Berlin.

## Proxy (optional)

Use the standard `HTTPS_PROXY` environment variable (or `ALL_PROXY` and `NO_PROXY`). HTTP, HTTPS, SOCKS5, SOCKS5h, and authenticated proxy URLs are supported.

To keep credentials in a local `.env` file instead of your MCP client configuration:

```bash
cp .env.example .env
# Edit .env and replace the example proxy URL
uv run mediamarkt-saturn-mcp --config --env-file .env
```

Copy the generated JSON into your MCP client. It uses `uv` to load the file at startup without placing credentials in the generated configuration. `.env` is ignored by Git. Percent-encode special characters in credentials (for example, `@` as `%40`). Existing environment variables take precedence over `.env` values.

To check the proxy, run `uv run --env-file .env mediamarkt-saturn-mcp --check mediamarkt`. Alternatively, set `HTTPS_PROXY` directly in the MCP client's `env`. Remove any previous `MMS_PROXY` or `MMS_PROXY_FILE` settings and migrate to `HTTPS_PROXY`; requests fail until the legacy settings are removed.

## Notes

- Search results and marketplace offers may be incomplete. Searches redirected to landing pages return only visible products with embedded data. Brand and price filters apply locally to this partial set; delivery filters and pagination remain unavailable.
- `include_offers` loads each product page, so it takes longer. Failed lookups include an `enrichment_error_code` on the affected product.
- Availability is `available`, `unavailable`, `partial`, or `unknown`; original retailer values are retained. Pickup is not a reservation or exact stock count.
- Results include `observed_at` and cache metadata. The process-local cache lasts 30 seconds for searches, 60 for products, 5 minutes for stores, and 10 seconds for pickup. Use `fresh: true` to bypass it. This does not bypass any retailer-side cache.
- Tool failures keep MCP `is_error: true` and include `structured_content.error.code` and `message` (for example `blocked`, `rate_limited`, `network_error`, or `retailer_changed`).
- This is an unofficial integration. Shop interfaces and access restrictions can change.

## Development

Shop requests live in `mediamarkt_mcp/shop/`, MCP response schemas in `mediamarkt_mcp/mcp_api/`, and tool registration in `mediamarkt_mcp/server.py`. Run `uv run ruff check mediamarkt_mcp tests` for lint checks. GitHub Actions tests Python 3.11–3.14 and verifies the built wheel.

## Diagnostics

```bash
uv run mediamarkt-saturn-mcp --check mediamarkt
uv run mediamarkt-saturn-mcp --check saturn
uv run mediamarkt-saturn-mcp --check mediamarkt --country ch --language fr
uv run python -m unittest discover -s tests -v
```

