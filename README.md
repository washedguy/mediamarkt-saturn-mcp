# MediaMarkt & Saturn MCP

Search products, compare prices, find stores, and check pickup availability at MediaMarkt, MediaWorld, and Saturn storefronts. No account or API key required.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and add this to your MCP client configuration:

```json
{
  "mcpServers": {
    "mediamarkt-saturn": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/washedguy/mediamarkt-saturn-mcp",
        "mediamarkt-saturn-mcp"
      ]
    }
  }
}
```

Restart your MCP client. If it cannot find `uvx`, use the absolute path to the `uvx` executable as `command`. If `mcpServers` already exists, add only the `mediamarkt-saturn` entry. To pin a specific revision, append `@<tag-or-commit>` to the Git URL.

## Tools

| Tool | What it does |
| --- | --- |
| `list_storefronts` | List supported countries, shop languages, currencies, and delivery filters. |
| `search_products` | Search by keyword, brand, price, and home delivery. Set `include_offers: true` to also fetch linked variants and marketplace offers. |
| `browse_page` | Explore shop brand, category, offer and campaign pages, including `related_pages` from a brand hub. |
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

Set the standard `HTTPS_PROXY` environment variable in your MCP client configuration (or use `ALL_PROXY` and `NO_PROXY`):

```json
"env": {
  "HTTPS_PROXY": "http://username:password@proxy.example.com:8080"
}
```

Add `env` beside `command` and `args` in the `mediamarkt-saturn` entry. HTTP, HTTPS, SOCKS5, SOCKS5h, and authenticated proxy URLs are supported. Percent-encode special characters in credentials (for example, `@` as `%40`).

For a local checkout, you can instead copy `.env.example` to `.env`, edit it, and run `uv run mediamarkt-saturn-mcp --config --env-file .env`. The generated configuration loads the Git-ignored file using `uv` without including its contents. Existing environment variables take precedence. Remove previous `MMS_PROXY` or `MMS_PROXY_FILE` settings and migrate to `HTTPS_PROXY`; requests fail until the old settings are removed.

## Notes

- Search results may include unrelated products, even for nonsense queries; `total_products` is the shop's count, not a verified match count. Marketplace offers may be incomplete. Redirects return visible products with embedded data. Category, brand and offer listings can be paginated when the shop exposes a listing; its criteria may differ from the search. Other landing pages show curated products and cannot be paginated. Brand and price filters apply locally; delivery filters are unavailable on redirects.
- `include_offers` loads each product page, so it takes longer. Failed lookups include an `enrichment_error_code` on the affected product.
- Availability is `available`, `unavailable`, `partial`, or `unknown`; original retailer values are retained. Pickup is not a reservation or exact stock count.
- Results include `observed_at` and cache metadata. The process-local cache lasts 30 seconds for searches, 60 for products, 5 minutes for stores, and 10 seconds for pickup. Use `fresh: true` to bypass it. This does not bypass any retailer-side cache.
- Tool failures keep MCP `is_error: true` and include `structured_content.error.code` and `message` (for example `blocked`, `rate_limited`, `network_error`, or `retailer_changed`).
- This is an unofficial integration. Shop interfaces and access restrictions can change.

## Development

To work on the server locally (Python 3.11+):

```bash
git clone https://github.com/washedguy/mediamarkt-saturn-mcp.git
cd mediamarkt-saturn-mcp
uv sync --frozen
uv run mediamarkt-saturn-mcp --config
```

Shop requests live in `mediamarkt_mcp/shop/`, response schemas in `mediamarkt_mcp/mcp_api/`, and tools in `mediamarkt_mcp/server.py`. Run `uv run ruff check mediamarkt_mcp tests` for lint checks. GitHub Actions tests Python 3.11–3.14 and verifies the built wheel.

## Diagnostics

From a local checkout:

```bash
uv run mediamarkt-saturn-mcp --check mediamarkt
uv run mediamarkt-saturn-mcp --check saturn
uv run mediamarkt-saturn-mcp --check mediamarkt --country ch --language fr
uv run python -m unittest discover -s tests -v
```

## License

[MIT](LICENSE)
