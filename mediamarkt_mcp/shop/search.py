"""Search storefront pages and handle redirected listings."""
import json
import re
from urllib.parse import quote, urlencode, urljoin, urlsplit
from .config import DELIVERY_FILTERS
from .errors import RetailerError
from .http import _session, paced, request_error
from .parsing import _ProductLinks, _delivery

async def search_page(self, query, page=1, filters=None):
    """Read the public search page's server-rendered product state."""
    async with _session(timeout=20) as session:
        async with paced():
            try:
                params = [("query", query), ("page", str(page))] + [("filter", value) for value in (filters or [])]
                url = f"{self.base}/{self.language}/search.html?{urlencode(params, quote_via=quote)}"
                response = await session.get(url)
            except Exception as exc:
                raise request_error("Search page request failed", exc) from exc
    if response.status_code != 200:
        raise RetailerError(f"Search page returned HTTP {response.status_code}.")
    marker = "window.__PRELOADED_STATE__ = "
    if marker not in response.text:
        raise RetailerError("Search page did not contain product data; the retailer may have changed the page.")
    try:
        raw = response.text.split(marker, 1)[1]
        # The retailer embeds JavaScript's undefined in otherwise JSON-compatible state.
        state = json.JSONDecoder().raw_decode(re.sub(r"(?<=:)undefined(?=[,}])", "null", raw))[0]["apolloState"]
        # Some redirects (for example a brand page) embed a searchV4 object of
        # their own. It may discard the user's filters and must remain partial.
        final_path = urlsplit(str(response.url)).path
        if final_path != f"/{self.language}/search.html":
            return self._redirected_search(state, response, query, page, filters)
        searches = [value for key, value in state["ROOT_QUERY"].items() if key.startswith("searchV4:")]
        if len(searches) == 0:
            return self._redirected_search(state, response, query, page, filters)
        if len(searches) != 1: raise ValueError("Search result is ambiguous")
        result = searches[0]
        products = []
        prefix = f"GraphqlProduct:{self.sales_line}:{self.language}-{self.country.upper()}:"
        for key, product in state.items():
            if not key.startswith(prefix): continue
            pid = str(product.get("id") or key[len(prefix):])
            feature_id = f"{self.sales_line}:{self.language}:{pid}"
            price = state.get(f"CofrPriceFeature:{feature_id}") or next((value for key, value in state.items() if key.startswith("CofrPriceFeature:") and isinstance(value, dict) and value.get("id") == feature_id), {})
            delivery = (state.get(f"CofrDeliveryFeature:{feature_id}") or {}).get("delivery") or {}
            products.append({"id": pid, "title": product.get("title"), "brand": product.get("manufacturer"), "price": (price.get("price") or {}).get("amount"), "currency": price.get("currency") or self.currency, "url": urljoin(self.base, product["url"]) if product.get("url") else None, "delivery": _delivery(delivery)})
        if result.get("totalProducts", 0) and not products:
            raise ValueError("Search results contained no products")
        paging = result.get("paging") or {}
        current_page = paging.get("currentPage") or page
        last_page = min(paging.get("pageCount") or current_page, paging.get("maxPage") or 30, 30)
        return {"retailer": self.retailer, "country": self.country, "language": self.language, "query": query, "products": products,
                "count": len(products), "total_products": result.get("totalProducts"),
                "page": current_page, "next_page": current_page + 1 if current_page < last_page else None,
                "paging": {"current_page": current_page, "page_count": paging.get("pageCount"), "max_page": last_page},
                "source": "search_page", "coverage": "search_page", "note": "The retailer may include recommendations unrelated to the query."}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RetailerError(f"Could not parse the retailer search page: {exc}") from exc


def _redirected_search(self, state, response, query, page, filters):
    final_url = str(response.url)
    parts = urlsplit(final_url)
    if parts.scheme != "https" or parts.hostname not in self.hosts or not parts.path.startswith(f"/{self.language}/") or parts.path == f"/{self.language}/search.html":
        raise RetailerError("The search response did not contain a product list or a supported storefront redirect.")
    if page != 1:
        raise RetailerError("The retailer redirected this search to a landing page, which does not support pagination. Retry on page 1.", code="unsupported")
    for item in filters or []:
        if not item.startswith(("brand:", "currentprice:")):
            raise RetailerError("The retailer redirected this search to a landing page; the delivery filter cannot be applied reliably.", code="unsupported")
    parser = _ProductLinks()
    parser.feed(response.text)
    products = []
    for href in parser.links:
        pid = re.search(r"-(\d+)\.html$", href).group(1)
        feature_id = f"{self.sales_line}:{self.language}:{pid}"
        core = state.get(f"CofrCoreFeature:{feature_id}") or {}
        graph = state.get(f"GraphqlProduct:{self.sales_line}:{self.language}-{self.country.upper()}:{pid}") or {}
        title = core.get("productName") or graph.get("title")
        if not title:
            continue
        price = state.get(f"CofrPriceFeature:{feature_id}") or next((v for k, v in state.items() if k.startswith("CofrPriceFeature:") and isinstance(v, dict) and v.get("id") == feature_id), {})
        delivery = (state.get(f"CofrDeliveryFeature:{feature_id}") or {}).get("delivery") or {}
        products.append({"id": pid, "title": title, "brand": core.get("manufacturerName") or graph.get("manufacturer"),
            "price": (price.get("price") or {}).get("amount"), "currency": price.get("currency") or self.currency,
            "url": urljoin(self.base, href), "delivery": _delivery(delivery)})
    for item in filters or []:
        field, value = item.split(":", 1)
        if field == "brand":
            products = [p for p in products if p["brand"] and p["brand"].casefold() == value.casefold()]
        elif field == "currentprice":
            number = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
            match = re.fullmatch(rf"({number})-({number})", value)
            if not match:
                raise RetailerError("Invalid price filter.", code="invalid_input")
            minimum, maximum = map(float, match.groups())
            products = [p for p in products if isinstance(p["price"], (int, float)) and minimum <= p["price"] <= maximum]
    return {"retailer": self.retailer, "country": self.country, "language": self.language, "query": query, "products": products, "count": len(products),
        "total_products": None, "page": 1, "next_page": None,
        "paging": {"current_page": 1, "page_count": None, "max_page": None}, "source": "redirected_page", "coverage": "partial_landing_page",
        "redirected_url": f"{self.base}{parts.path}",
        "local_filters": list(filters or []),
        "note": "The retailer redirected the search to a landing page. Results are limited to visible products with embedded data and may be unrelated. Brand and price filters are applied locally; products with missing values are excluded. Delivery filters and pagination are unavailable."}


async def search(self, query, page=1, brand=None, min_price=None, max_price=None, delivery_only=False):
    if delivery_only and (self.country, self.language) not in DELIVERY_FILTERS:
        raise RetailerError("The in-stock delivery filter is not verified for this storefront and language.")
    filters = []
    if brand: filters.append(f"brand:{brand}")
    if min_price is not None or max_price is not None: filters.append(f"currentprice:{min_price if min_price is not None else 0}-{max_price if max_price is not None else 999999}")
    if delivery_only: filters.append(f"availabilityText:{DELIVERY_FILTERS[(self.country, self.language)]}")
    return await self.search_page(query, page, filters)

