"""Parse storefront pages and their product relationships."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from .errors import RetailerError

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1
        elif tag in ("p", "li", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class _ProductLinks(HTMLParser):
    """Collect product links in rendered page order, excluding embedded scripts."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            try:
                parts = urlsplit(href)
            except ValueError:
                return
            if (not parts.scheme and not parts.netloc
                    and re.fullmatch(r"/(?:de|fr|it|nl|es|pl|hu|tr)/product/[^/?#]+-\d+\.html", parts.path)
                    and parts.path not in self.links):
                self.links.append(parts.path)


class _BrandLinks(HTMLParser):
    """Collect child pages of the current brand hub, not navigation links."""
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.prefix = path.rstrip('/') + '/'
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        try:
            parts = urlsplit(dict(attrs).get('href') or '')
        except ValueError:
            return
        if (not parts.scheme and not parts.netloc and parts.path.startswith(self.prefix)
                and '..' not in parts.path.split('/') and parts.path not in self.links):
            self.links.append(parts.path)


def _plain_text(value):
    if not value:
        return None
    parser = _TextExtractor()
    parser.feed(value)
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip()) or None


def _apollo_state(text):
    marker = "window.__PRELOADED_STATE__ = "
    if marker not in text:
        raise RetailerError("Page did not contain the retailer's product data.")
    try:
        raw = text.split(marker, 1)[1]
        return json.JSONDecoder().raw_decode(re.sub(r"(?<=:)undefined(?=[,}])", "null", raw))[0]["apolloState"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RetailerError("Could not parse the retailer's embedded product data.") from exc


def _is_preorder(raw_status, retailer_code):
    values = " ".join(str(value or "") for value in (raw_status, retailer_code)).upper()
    return any(token in values for token in ("NOT_RELEASED", "PREORDER", "PRE_ORDER", "PRE-ORDER", "VORBESTELL"))


def _availability(raw):
    # Preserve the shop's status separately; never infer unknown values as unavailable.
    return {"AVAILABLE": "available", "NOT_AVAILABLE": "unavailable", "PARTIALLY_AVAILABLE": "partial"}.get(raw, "unknown")


def _delivery(data):
    data = data or {}
    raw = data.get("displayStatus")
    code = data.get("deliveryStatus")
    preorder = _is_preorder(raw, code)
    status = "preorder" if preorder else _availability(raw)
    return {"status": status, "retailer_status": raw,
            "retailer_code": code,
            "earliest": (data.get("fulfillmentTime") or {}).get("earliest"),
            "preorder": preorder,
            "is_preorder": preorder}


def _ref(state, value):
    return state.get(value.get("__ref"), {}) if isinstance(value, dict) and "__ref" in value else (value or {})


def _related_products(state, product, product_id):
    variants = []
    seen = set()
    for group in product.get("variants") or []:
        for item in group.get("variantProducts") or []:
            pid = str(item.get("productId") or "")
            if not pid or pid == product_id or pid in seen:
                continue
            seen.add(pid)
            related = _ref(state, item.get("product"))
            variants.append({"product_id": pid, "title": item.get("displayName") or related.get("title"),
                "variant_name": group.get("variantName"), "variant_value": item.get("variantValue"),
                "url": related.get("url")})
    return variants


def _marketplace_offers(state, sales_line, product_id):
    direct_match = state.get(f"GraphqlProductMatch:{product_id}")
    matches = [direct_match] if isinstance(direct_match, dict) else []
    if not matches:
        matches = [value for key, value in state.items() if key.startswith("GraphqlProductMatch:")
                   and isinstance(value, dict) and str(value.get("marketplaceProductId")) == product_id]
    refs = []
    for match in matches:
        for key, value in match.items():
            if key.startswith("marketplaceOffersV3(") or key in ("bestMarketplaceOffers", "bestRefurbishedMarketplaceOffer"):
                refs.extend(value if isinstance(value, list) else [value])
    offers = []
    seen = set()
    for ref in refs:
        offer = _ref(state, ref)
        if not isinstance(offer, dict) or offer.get("offerId") is None:
            continue
        oid = str(offer["offerId"])
        if oid in seen:
            continue
        seen.add(oid)
        pid = str(offer["productId"]) if offer.get("productId") is not None else None
        cofr = offer.get("cofrProductAggregate({})") or {}
        delivery = _ref(state, cofr.get("cofrDeliveryFeature"))
        options = offer.get("deliveryOptions") or []
        costs = [o.get("costAmount") for o in options if o.get("costAmount") is not None]
        offers.append({"offer_id": oid, "product_id": pid, "seller_id": str(offer["sellerId"]) if offer.get("sellerId") is not None else None,
            "seller_name": offer.get("sellerName"), "seller_rating": offer.get("sellerRating"),
            "price": offer.get("price"), "currency": offer.get("currencyIsoCode"),
            "shipping_cost": min(costs) if costs else None, "condition": offer.get("offerCondition"),
            "delivery": _delivery(delivery.get("delivery")), "is_best_offer": offer.get("isBestOffer")})
    return offers

