"""Public storefront client, composed from focused request modules."""
from urllib.parse import urlsplit
from .shop import http, products, search as search_api, stores as store_api
from .shop.config import STOREFRONTS, cofr_config
from .shop.errors import RetailerError as RetailerError


class Client:
    def __init__(self, retailer: str = "mediamarkt", country: str = "de", language: str | None = None):
        if retailer not in ("mediamarkt", "saturn"):
            raise ValueError("Unknown retailer")
        if country not in STOREFRONTS:
            raise ValueError(f"Unsupported country: {country}")
        if retailer == "saturn" and country != "de":
            raise ValueError("Saturn is supported only in Germany (country=de).")
        host, currency, languages = STOREFRONTS[country]
        language = language or languages[0]
        if language not in languages:
            raise ValueError(f"Unsupported language for {country}; choose: {', '.join(languages)}.")
        self.retailer = retailer
        self.country = country
        self.language = language
        self.currency = currency
        self.sales_line = "Saturn" if retailer == "saturn" else "Media"
        self.base = "https://www.saturn.de" if retailer == "saturn" else f"https://{host}"
        self.hosts = {urlsplit(self.base).hostname, urlsplit(self.base).hostname.removeprefix("www.")}
        self.config = cofr_config(self.base)


    async def gql(self, operation, variables, cacheable=True):
        return await http.gql(self, operation, variables, cacheable)

    async def search_page(self, query, page=1, filters=None):
        return await search_api.search_page(self, query, page, filters)

    async def browse_page(self, url, page=1):
        return await search_api.browse_page(self, url, page)

    def _redirected_search(self, state, response, query, page, filters):
        return search_api._redirected_search(self, state, response, query, page, filters)

    async def search(self, query, page=1, brand=None, min_price=None, max_price=None, delivery_only=False):
        return await search_api.search(self, query, page, brand, min_price, max_price, delivery_only)

    async def product(self, reference):
        return await products.product(self, reference)

    async def stores(self, query):
        return await store_api.stores(self, query)

    async def pickup(self, store_id, product_ids):
        return await store_api.pickup(self, store_id, product_ids)
