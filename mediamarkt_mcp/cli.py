"""Command-line entry point and live diagnostics."""
import argparse
import asyncio
import json
import shutil
from pathlib import Path
import sys
from .client import Client, RetailerError
from .shop.config import STOREFRONTS


async def _check(retailer: str, country: str = "de", language: str | None = None) -> int:
    stage = "search_products"
    try:
        client = Client(retailer, country, language)
        search = await client.search("Nintendo Switch")
        print(f"{retailer}: {stage} OK ({len(search['products'])} products)", flush=True)
        if not search["products"] or not search["products"][0].get("id"):
            raise RetailerError("Search returned no usable product ID; cannot test product details or pickup.")
        product_id = search["products"][0]["id"]
        stage = "get_product"
        product = await client.product(product_id)
        if not product.get("found"):
            raise RetailerError(f"Could not resolve product {product_id}: {product.get('reason')}")
        print(f"{retailer}: {stage} OK (product {product_id})", flush=True)
        stage = "find_stores"
        cities = {"de": "Berlin", "at": "Wien", "ch": "Zürich", "nl": "Amsterdam", "be": "Brussel", "es": "Madrid", "it": "Milano", "pl": "Warszawa", "hu": "Budapest", "tr": "Istanbul"}
        stores = await client.stores(cities[country])
        print(f"{retailer}: {stage} OK ({len(stores['stores'])} stores)", flush=True)
        if not stores["stores"]:
            raise RetailerError("Store lookup returned no stores; cannot test pickup.")
        stage = "check_pickup_availability"
        result = await client.pickup(stores["stores"][0]["id"], [product_id])
        print(f"{retailer}: {stage} OK (status: {result['products'][0]['status']})", flush=True)
        return 0
    except (RetailerError, ValueError) as exc:
        print(f"{retailer}: {stage} failed: {exc}", file=sys.stderr)
        return 1

def main():
    parser = argparse.ArgumentParser(description="MediaMarkt, MediaWorld & Saturn MCP server. Run without arguments to serve over stdio.")
    parser.add_argument("--config", action="store_true", help="Print MCP client configuration for this Python environment and exit.")
    parser.add_argument("--check", choices=["mediamarkt", "saturn"], metavar="RETAILER", help="Run a live connectivity check for mediamarkt or saturn and exit.")
    parser.add_argument("--country", choices=list(STOREFRONTS), default="de", help="Country for --check (default: de).")
    parser.add_argument("--language", choices=["de", "fr", "it", "nl", "es", "pl", "hu", "tr"], help="Storefront language for --check.")
    parser.add_argument("--env-file", metavar="PATH", help="With --config, generate a launcher that loads this dotenv file using uv.")
    args = parser.parse_args()
    env_file = str(Path(args.env_file).expanduser().resolve()) if args.env_file else None
    if env_file and not args.config:
        parser.error("--env-file requires --config; for diagnostics use uv run --env-file PATH")
    if args.config and args.check:
        parser.error("--config and --check cannot be combined")
    if args.config:
        config = {"command": sys.executable, "args": ["-m", "mediamarkt_mcp.server"]}
        if env_file:
            if not Path(env_file).is_file():
                parser.error("--env-file must point to an existing file")
            uv = shutil.which("uv")
            if not uv:
                parser.error("uv must be available on PATH to generate an --env-file configuration")
            config = {"command": str(Path(uv).resolve()), "args": ["run", "--no-project", "--env-file", env_file,
                     "--", sys.executable, "-m", "mediamarkt_mcp.server"]}
        print(json.dumps({"mcpServers": {"mediamarkt-saturn": config}}, indent=2))
    elif args.check:
        raise SystemExit(asyncio.run(_check(args.check, args.country, args.language)))
    else:
        from .server import mcp
        mcp.run(transport="stdio")

