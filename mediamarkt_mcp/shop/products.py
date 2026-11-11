"""Retrieve product pages and their linked offers and variants."""
import re
from urllib.parse import urljoin, urlsplit
from .errors import RetailerError
from .http import _session, paced, request_error
from .parsing import _apollo_state, _delivery, _marketplace_offers, _plain_text, _related_products

async def product(self, reference):
    """Resolve an ID or URL and read product details from the product page."""
    if reference.isdigit():
        # The storefront resolves ID-only paths to canonical product pages.
        url = f"{self.base}/{self.language}/product/_-{reference}.html"
    else:
        url = reference
    try:
        parts = urlsplit(url)
        valid_host = parts.hostname in self.hosts and parts.username is None and parts.port is None
    except ValueError as exc:
        raise RetailerError("Invalid product URL; check the hostname and port.", code="invalid_input") from exc
    if parts.scheme != "https" or not valid_host:
        raise RetailerError("Use an HTTPS product URL for the selected storefront or a product ID.", code="invalid_input")
    match = re.fullmatch(rf"/{self.language}/product/[^/]*-(\d+)\.html", parts.path)
    if not match:
        raise RetailerError("The product URL must end with a numeric product ID and .html.", code="invalid_input")
    product_id = match.group(1)
    url = f"{self.base}{parts.path}"
    async with _session(timeout=20) as session:
        for _ in range(4):
            async with paced():
                try:
                    response = await session.get(url, allow_redirects=False)
                except Exception as exc:
                    raise request_error("Product page request failed", exc) from exc
            if response.status_code not in (301, 302, 303, 307, 308):
                break
            target = urljoin(url, response.headers.get("location", ""))
            try:
                next_parts = urlsplit(target)
                next_match = re.fullmatch(rf"/{self.language}/product/[^/]*-(\d+)\.html", next_parts.path)
                valid_redirect = (next_parts.scheme == "https" and next_parts.hostname in self.hosts
                                  and next_parts.username is None and next_parts.port is None and next_match)
            except ValueError as exc:
                raise RetailerError("The product page redirected to an invalid location.", code="retailer_changed") from exc
            if not valid_redirect:
                raise RetailerError("The product page redirected to an unsupported location.", code="retailer_changed")
            url = f"https://{next_parts.netloc}{next_parts.path}"
        else:
            raise RetailerError("Product page redirected too many times.")
    if response.status_code == 404:
        return {"retailer": self.retailer, "country": self.country, "language": self.language, "reference": reference, "found": False, "product": None, "reason": "product_url_not_found"}
    if response.status_code != 200:
        raise RetailerError(f"Product page returned HTTP {response.status_code}; check the link or retailer access.")
    state = _apollo_state(response.text)
    product = state.get(f"GraphqlProduct:{self.sales_line}:{self.language}-{self.country.upper()}:{product_id}")
    if not isinstance(product, dict):
        if urlsplit(url).path != parts.path:
            return {"retailer": self.retailer, "country": self.country, "language": self.language, "reference": reference, "found": False, "product": None, "reason": "requested_product_not_on_redirected_page"}
        raise RetailerError("The page did not contain details for the requested product; the retailer may have changed the page.")
    feature_id = f"{self.sales_line}:{self.language}:{product_id}"
    price = state.get(f"CofrPriceFeature:{feature_id}") or next((v for k, v in state.items() if k.startswith("CofrPriceFeature:") and isinstance(v, dict) and v.get("id") == feature_id), {})
    delivery = (state.get(f"CofrDeliveryFeature:{feature_id}") or {}).get("delivery") or {}
    core = state.get(f"CofrCoreFeature:{feature_id}") or {}
    stats = core.get("reviewStatistics") or {}
    media = state.get(f"CofrMediaAssetsFeature:{feature_id}") or {}
    images = [{"url": img.get("link"), "alt": img.get("altText")} for img in (media.get("productImages") or []) if img.get("link")]
    groups_ref = product.get("featureGroupsWithProductId") or {}
    feature_groups = state.get(groups_ref.get("__ref"), {}).get("featureGroups") or []
    features = []
    for group in feature_groups:
        items = []
        for ref in group.get("features") or []:
            item = state.get(ref.get("__ref"), {}) if isinstance(ref, dict) else {}
            if item.get("name"):
                items.append({"name": item["name"], "value": item.get("value"), "unit": item.get("unit")})
        if items:
            features.append({"group": group.get("featureGroupName"), "items": items})
    delivery_data = _delivery(delivery)
    details = {"id": product_id, "title": product.get("title"), "brand": product.get("manufacturer"),
        "price": (price.get("price") or {}).get("amount"), "currency": price.get("currency") or self.currency,
        "url": urljoin(self.base, product.get("url") or url), "resolved_url": url,
        "delivery": delivery_data,
        "preorder": delivery_data.get("preorder", False),
        "is_preorder": delivery_data.get("is_preorder", False),
        "ean": product.get("ean") or core.get("ean"), "variants": [{**v, "url": urljoin(self.base, v["url"]) if v["url"] else None} for v in _related_products(state, product, product_id)], "marketplace_offers": _marketplace_offers(state, self.sales_line, product_id), "offers_coverage": "embedded_page_only", "description": _plain_text(product.get("description")),
        "description_marketing": _plain_text(product.get("descriptionMarketing")), "images": images,
        "rating": {"average": stats.get("averageOverallRating"), "count": stats.get("totalReviewCount"), "scale": stats.get("overallRatingRange")},
        "categories": [item.get("name") for item in product.get("breadcrumbs") or [] if item.get("name")],
        "features": features}
    return {"retailer": self.retailer, "country": self.country, "language": self.language, "reference": reference, "found": True, "product": details, "reason": None}

