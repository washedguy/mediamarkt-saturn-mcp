# MediaMarkt & Saturn MCP

MCP server for MediaMarkt, MediaWorld, and Saturn products, prices, and availability.

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

## Notes

- Set `HTTPS_PROXY` (or `ALL_PROXY` and `NO_PROXY`) to configure a proxy.
- Search results and marketplace offers may be incomplete. `include_offers` loads product pages and can take longer.
- Pickup availability is an estimate, not a reservation or exact stock count. Set `fresh: true` to bypass the local cache.
- This is an unofficial integration and storefront behavior may change.

## Development

To work on the server locally (Python 3.11+):

```bash
git clone https://github.com/washedguy/mediamarkt-saturn-mcp.git
cd mediamarkt-saturn-mcp
uv sync --frozen
uv run mediamarkt-saturn-mcp --config
```

Run `uv run python -m unittest discover -s tests -v` for tests and `uv run ruff check mediamarkt_mcp tests` for linting.

## Author

**[washed.dev](https://washed.dev)** · Building websites and web apps for your business

## License

[MIT](LICENSE)
