"""Search storefront pages and handle redirected listings."""
import json
import re
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit
from .config import DELIVERY_FILTERS
from .errors import RetailerError
from .http import _session, paced, request_error
from .parsing import _BrandLinks, _ProductLinks, _apollo_state, _delivery


def _listing_keys(state, path, language):
    if path.startswith(f"/{language}/category/"):
        prefix = "categoryV4:"
    elif path.startswith((f"/{language}/brand/", f"/{language}/list/")):
        prefix = "searchV4:"
    else:
        return []
    return [k for k, v in state.get("ROOT_QUERY", {}).items() if k.startswith(prefix) and isinstance(v, dict)]


async def browse_page(self, url, page=1):
    """Browse a shop landing page returned by search or brand discovery."""
    try:
        parts = urlsplit(url)
        decoded_path = unquote(parts.path)
        valid = (parts.scheme == "https" and parts.hostname in self.hosts and parts.username is None
                 and parts.port is None and parts.path.startswith(tuple(f"/{self.language}/{kind}/" for kind in ("brand", "list", "category", "campaign")))
                 and not parts.query and not parts.fragment and ".." not in decoded_path.split("/") and "\\" not in decoded_path)
    except ValueError:
        valid = False
    if not valid:
        raise RetailerError("Use an HTTPS brand, list, category or campaign URL from the selected storefront, without query parameters or fragments.", code="invalid_input")
    target = f"{self.base}{parts.path}?{urlencode({'page': page})}"
    async with _session(timeout=20) as session:
        for _ in range(4):
            async with paced():
                try:
                    response = await session.get(target, allow_redirects=False)
                except Exception as exc:
                    raise request_error("Listing page request failed", exc) from exc
            if response.status_code not in (301, 302, 303, 307, 308):
                break
            target = urljoin(target, response.headers.get("location", ""))
            try:
                redirected = urlsplit(target)
                valid_redirect = (redirected.scheme == "https" and redirected.hostname in self.hosts
                                  and redirected.username is None and redirected.port is None and redirected.path == parts.path)
            except ValueError:
                valid_redirect = False
            if not valid_redirect:
                raise RetailerError("The listing page redirected to an unsupported location.", code="retailer_changed")
        else:
            raise RetailerError("The listing page redirected too many times.")
    final = urlsplit(str(response.url))
    if response.status_code != 200 or final.scheme != "https" or final.hostname not in self.hosts or final.path != parts.path:
        raise RetailerError("The listing page could not be retrieved reliably.")
    result = self._redirected_search(_apollo_state(response.text), response, url, page, [])
    result["note"] = result["note"].replace("The retailer redirected the search to a", "This is a", 1)
    return result

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
    # Redirects may drop the requested page. Only paginate identifiable listings.
    destination = urlsplit(str(response.url))
    if (page > 1 and destination.scheme == "https" and destination.hostname in self.hosts
            and destination.username is None and destination.port is None
            and destination.path.startswith((f"/{self.language}/category/", f"/{self.language}/brand/", f"/{self.language}/list/"))):
        original_keys = _listing_keys(_apollo_state(response.text), destination.path, self.language)
    else:
        original_keys = []
    if len(original_keys) == 1:
        url = f"{self.base}{destination.path}?{urlencode({'page': page})}"
        async with _session(timeout=20) as session:
            async with paced():
                try:
                    response = await session.get(url)
                except Exception as exc:
                    raise request_error("Category page request failed", exc) from exc
        target = urlsplit(str(response.url))
        if (response.status_code != 200 or target.scheme != "https" or target.hostname not in self.hosts
                or target.path != destination.path):
            raise RetailerError("The redirected listing page could not be retrieved reliably.")
        if _listing_keys(_apollo_state(response.text), target.path, self.language) != original_keys:
            raise RetailerError("The retailer returned a different listing for the requested page.", code="retailer_changed")
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
                "source": "search_page", "coverage": "search_page", "note": "The retailer may return products unrelated to the query. total_products is the retailer's count, not a count of verified keyword matches."}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RetailerError(f"Could not parse the retailer search page: {exc}") from exc


def _redirected_search(self, state, response, query, page, filters):
    final_url = str(response.url)
    parts = urlsplit(final_url)
    if parts.scheme != "https" or parts.hostname not in self.hosts or not parts.path.startswith(f"/{self.language}/") or parts.path == f"/{self.language}/search.html":
        raise RetailerError("The search response did not contain a product list or a supported storefront redirect.")
    keys = _listing_keys(state, parts.path, self.language)
    listing = None
    if len(keys) == 1:
        try:
            listing_args = json.loads(keys[0].split(":", 1)[1])
        except (ValueError, TypeError) as exc:
            raise RetailerError("Could not verify the redirected listing.") from exc
        if not isinstance(listing_args, dict):
            raise RetailerError("Could not verify the redirected listing.")
        if keys[0].startswith("categoryV4:") and listing_args.get("filters"):
            raise RetailerError("The redirected category has retailer filters that cannot be verified across pages.", code="unsupported")
        listing = state["ROOT_QUERY"][keys[0]]
        if not (listing.get("paging") or {}).get("currentPage"):
            listing = None
    paging = (listing or {}).get("paging") or {}
    if listing and paging.get("currentPage") != page:
        raise RetailerError("The retailer did not return the requested listing page.", code="retailer_changed")
    if page != 1 and not listing:
        raise RetailerError("The retailer redirected this search to a landing page, which does not support pagination. Retry on page 1.", code="unsupported")
    for item in filters or []:
        if not item.startswith(("brand:", "currentprice:")):
            raise RetailerError("The retailer redirected this search to a landing page; the delivery filter cannot be applied reliably.", code="unsupported")
    parser = _ProductLinks()
    parser.feed(response.text)
    related_pages = []
    if parts.path.startswith(f"/{self.language}/brand/"):
        brand_links = _BrandLinks(parts.path)
        brand_links.feed(response.text)
        related_pages = [urljoin(self.base, path) for path in brand_links.links[:30]]
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
    last_page = min(paging.get("pageCount") or page, paging.get("maxPage") or 30, 30) if listing else None
    return {"retailer": self.retailer, "country": self.country, "language": self.language, "query": query, "products": products, "count": len(products),
        "total_products": None, "page": page, "next_page": page + 1 if last_page and page < last_page else None,
        "paging": {"current_page": page, "page_count": paging.get("pageCount") if listing else None, "max_page": last_page}, "source": "redirected_page", "coverage": ("redirected_category" if keys[0].startswith("categoryV4:") else "redirected_listing") if listing else "partial_landing_page",
        "redirected_url": f"{self.base}{parts.path}",
        "related_pages": related_pages,
        "local_filters": list(filters or []),
        "note": ("The retailer redirected the search to a category, brand or offer listing. Its criteria may differ from the original query. Results are limited to visible products with embedded data and may be unrelated. Pagination browses that listing; brand and price filters apply locally to each page, and products with missing values are excluded. Delivery filters are unavailable." if listing else
                 "The retailer redirected the search to a landing page. Results are limited to visible products with embedded data and may be unrelated. Brand and price filters are applied locally; products with missing values are excluded. Delivery filters and pagination are unavailable.")}


async def search(self, query, page=1, brand=None, min_price=None, max_price=None, delivery_only=False):
    if delivery_only and (self.country, self.language) not in DELIVERY_FILTERS:
        raise RetailerError("The in-stock delivery filter is not verified for this storefront and language.")
    filters = []
    if brand: filters.append(f"brand:{brand}")
    if min_price is not None or max_price is not None: filters.append(f"currentprice:{min_price if min_price is not None else 0}-{max_price if max_price is not None else 999999}")
    if delivery_only: filters.append(f"availabilityText:{DELIVERY_FILTERS[(self.country, self.language)]}")
    return await self.search_page(query, page, filters)

