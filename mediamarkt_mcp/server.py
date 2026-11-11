"""English-language MCP tools for MediaMarkt and Saturn Germany."""
from typing import Annotated, Literal

from .mcp_api.server import StructuredMCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from .mcp_api.schemas import PickupResult, ProductResult, SearchResult, StorefrontList, StoreResult

from .client import Client, RetailerError, STOREFRONTS
from .shop.config import DELIVERY_FILTERS
from .shop.cache import cached_call

mcp = StructuredMCPServer("mediamarkt-saturn", instructions=(
    "Search MediaMarkt, MediaWorld and Saturn storefronts. Use list_storefronts to discover supported countries and shop languages. For marketplace offers or variants, use search_products with include_offers=true or get_product; embedded page offers can be incomplete. Use search_products to find product IDs and "
    "get_product to resolve exact product IDs or URLs and find_stores to find store IDs. Ask the user to choose when several stores match, then "
    "use check_pickup_availability for that store. Delivery is separate from pickup; "
    "unknown availability is not out of stock. Offers and variants are limited to data embedded on the product page. Prices and availability can change."
))
Retailer = Annotated[Literal["mediamarkt", "saturn"], Field(description="Storefront brand: mediamarkt (including MediaWorld in Italy) or saturn (Germany only).")]
Country = Annotated[Literal["de", "at", "ch", "nl", "be", "es", "it", "pl", "hu", "tr"], Field(description="Storefront country code. Defaults to de. Product and store IDs are country-specific.")]
Language = Annotated[Literal["de", "fr", "it", "nl", "es", "pl", "hu", "tr"] | None, Field(description="Shop language; defaults to the country's main language. Switzerland: de/fr/it; Belgium: nl/fr.")]

def _client(retailer, country, language):
    try:
        return Client(retailer, country, language)
    except ValueError as exc:
        raise ToolError(f"[invalid_input] {exc}") from exc

Query = Annotated[str, Field(min_length=1, max_length=200, description="Product keywords, model number, or EAN. Local-language terms may work best.")]

@mcp.tool(structured_output=True)
async def list_storefronts() -> StorefrontList:
    """List supported countries, retailers, shop languages, currencies and in-stock delivery-filter availability. Product and store IDs are country-specific. Italian MediaMarkt is called MediaWorld; Saturn is Germany only."""
    shops = [{"country": country, "retailer": "mediamarkt", "languages": list(languages), "default_language": languages[0], "currency": currency, "url": f"https://{host}", "delivery_filter_languages": [language for language in languages if (country, language) in DELIVERY_FILTERS]} for country, (host, currency, languages) in STOREFRONTS.items()]
    shops.append({"country": "de", "retailer": "saturn", "languages": ["de"], "default_language": "de", "currency": "EUR", "url": "https://www.saturn.de", "delivery_filter_languages": ["de"]})
    return StorefrontList.model_validate({"storefronts": shops})

@mcp.tool(structured_output=True)
async def search_products(
    query: Query,
    retailer: Retailer = "mediamarkt",
    country: Country = "de",
    language: Language = None,
    page: Annotated[int, Field(ge=1, le=30, description="Results page, starting at 1. Use next_page to continue.")] = 1,
    brand: Annotated[str | None, Field(min_length=1, max_length=100, description="Exact retailer brand name, e.g. SONY.")] = None,
    min_price: Annotated[float | None, Field(ge=0, description="Minimum price in the local currency.")] = None,
    max_price: Annotated[float | None, Field(ge=0, description="Maximum price in the local currency.")] = None,
    delivery_only: Annotated[bool, Field(description="Use the storefront in-stock delivery filter (not store pickup); unsupported for Spain, Italy and Türkiye.")] = False,
    include_offers: Annotated[bool, Field(description="Fetch each product page to include linked variants and embedded marketplace offers. Slower; results are not exhaustive.")] = False,
    fresh: Annotated[bool, Field(description="Bypass the process cache and request current shop data.")] = False,
) -> SearchResult:
    """Search the selected MediaMarkt, MediaWorld or Saturn storefront for product names, prices and home delivery. Search can return suggestions unrelated to the query; verify relevance. Redirected landing pages return only visible products with available data, may include unrelated products, and support local brand/price filters on visible products only, but not delivery filters or pagination. Set include_offers to inspect linked variants and embedded marketplace offers for each result; slower and not exhaustive. Use get_product for exact IDs or URLs. Returns pagination for more results."""
    if not query.strip():
        raise ToolError("[invalid_input] query must not be blank")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ToolError("[invalid_input] min_price must not exceed max_price")
    if brand is not None and not brand.strip():
        raise ToolError("[invalid_input] brand must not be blank")
    try:
        client = _client(retailer, country, language)
        search_args = (query.strip(), page, brand.strip() if brand else None, min_price, max_price, delivery_only)
        result = await cached_call("search", (retailer, country, language, *search_args), fresh,
                                   lambda: client.search(*search_args))
        if include_offers:
            for item in result["products"]:
                if not item.get("id"):
                    item["enrichment_error"] = "Product ID missing; page details unavailable."
                    item["enrichment_error_code"] = "retailer_changed"
                    continue
                try:
                    reference = item["url"] if item.get("url") else item["id"]
                    detail = await cached_call("product", (retailer, country, language, reference), fresh,
                                               lambda reference=reference: client.product(reference))
                    if not detail.get("found"):
                        item["enrichment_error"] = f"Product page unavailable: {detail.get('reason')}"
                        item["enrichment_error_code"] = "not_found"
                        continue
                    data = detail["product"]
                    for key in ("variants", "marketplace_offers", "offers_coverage"):
                        item[key] = data[key]
                    item["details_observed_at"] = detail["observed_at"]
                    item["details_cache"] = detail["cache"]
                except RetailerError as exc:
                    item["enrichment_error"] = str(exc)
                    item["enrichment_error_code"] = exc.code
        return SearchResult.model_validate(result)
    except RetailerError as exc:
        raise ToolError(f"[{exc.code}] {exc}") from exc

@mcp.tool(structured_output=True)
async def get_product(
    reference: Annotated[str, Field(min_length=1, max_length=500, description="Exact product ID or HTTPS product URL from the selected retailer. Use search_products for product names.")],
    retailer: Retailer = "mediamarkt",
    country: Country = "de",
    language: Language = None,
    fresh: Annotated[bool, Field(description="Bypass the process cache and request current shop data.")] = False,
) -> ProductResult:
    """Read product details from the product page by exact ID or product URL, including description, EAN, images, rating, variants, linked marketplace offers and specifications where available. Offers are limited to what the page embeds and are not necessarily complete. Returns found=false for a 404 URL or if the requested ID is absent from a redirected product page; this does not prove the product no longer exists."""
    if not reference.strip():
        raise ToolError("[invalid_input] reference must not be blank")
    try:
        client = _client(retailer, country, language)
        result = await cached_call("product", (retailer, country, language, reference.strip()), fresh,
                                   lambda: client.product(reference.strip()))
        return ProductResult.model_validate(result)
    except RetailerError as exc:
        raise ToolError(f"[{exc.code}] {exc}") from exc

@mcp.tool(structured_output=True)
async def find_stores(
    query: Annotated[str, Field(min_length=1, max_length=100, description="City, postal code, or store name in the selected country.")],
    retailer: Retailer = "mediamarkt",
    country: Country = "de",
    language: Language = None,
    fresh: Annotated[bool, Field(description="Bypass the process cache and request current shop data.")] = False,
) -> StoreResult:
    """Find stores in the selected country and language by location. Choose the intended store ID before checking pickup; do not assume the first result is the right one."""
    if not query.strip():
        raise ToolError("[invalid_input] query must not be blank")
    try:
        client = _client(retailer, country, language)
        result = await cached_call("stores", (retailer, country, language, query.strip()), fresh,
                                   lambda: client.stores(query.strip()))
        return StoreResult.model_validate(result)
    except RetailerError as exc:
        raise ToolError(f"[{exc.code}] {exc}") from exc

@mcp.tool(structured_output=True)
async def check_pickup_availability(
    store_id: Annotated[str, Field(min_length=1, max_length=50, description="Store ID returned by find_stores for the same retailer.")],
    product_ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=100)]], Field(min_length=1, max_length=48, description="One to 48 product IDs returned by search_products.")],
    retailer: Retailer = "mediamarkt",
    country: Country = "de",
    language: Language = None,
    fresh: Annotated[bool, Field(description="Bypass the process cache and request current shop data.")] = False,
) -> PickupResult:
    """Check pickup availability for products at one selected store. Use IDs from search_products and find_stores for the same retailer and country. Unknown means the retailer returned no status; a status for an unverified ID does not confirm the product exists. Availability is not a reservation or exact stock count."""
    if not store_id.strip() or any(not pid.strip() for pid in product_ids):
        raise ToolError("[invalid_input] Store and product IDs must not be blank")
    try:
        client = _client(retailer, country, language)
        ids = tuple(pid.strip() for pid in product_ids)
        result = await cached_call("pickup", (retailer, country, language, store_id.strip(), ids), fresh,
                                   lambda: client.pickup(store_id.strip(), list(ids)))
        return PickupResult.model_validate(result)
    except RetailerError as exc:
        raise ToolError(f"[{exc.code}] {exc}") from exc

def main():
    from .cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
