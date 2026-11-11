"""Find stores and check pickup availability."""
from .errors import RetailerError
from .parsing import _availability

async def stores(self, query):
    data = await self.gql("GetStoreSuggestions", {"limit": 25, "searchTerm": query}, False)
    suggestions = data.get("storeSuggestions")
    if not isinstance(suggestions, list): raise RetailerError("Store response did not contain suggestions; the API may have changed.")
    stores = []
    for item in suggestions:
        if item.get("type") != "OUTLET" or item.get("outlet_id") is None:
            continue
        address = item.get("address") or {}
        position = item.get("position") or {}
        stores.append({"id": str(item["outlet_id"]), "name": item.get("name"),
                       "address": {"street": address.get("street"), "house_number": address.get("houseNumber"), "postal_code": address.get("zipCode"), "city": address.get("city"), "country": address.get("countryCode")},
                       "position": {"latitude": position.get("lat"), "longitude": position.get("lng")},
                       "phone": item.get("phoneNumber")})
    return {"retailer": self.retailer, "country": self.country, "language": self.language, "query": query, "stores": stores, "count": len(stores)}


async def pickup(self, store_id, product_ids):
    from datetime import datetime, timezone
    products = []
    for i in range(0, len(product_ids), 12):
        batch = product_ids[i:i+12]
        data = await self.gql("GetCofrPickupFeaturePickups", {"productIds": batch, "storeId": store_id, "config": self.config}, False)
        aggregates = data.get("cofrProductAggregates")
        if not isinstance(aggregates, list): raise RetailerError("Pickup response did not contain availability; the API may have changed.")
        by_id = {}
        for aggregate in aggregates:
            feature = aggregate.get("cofrPickupFeature") or {}; parts = (feature.get("id") or "").split(":")
            if len(parts) >= 3: by_id[parts[2]] = {"status": _availability(feature.get("displayStatus")), "retailer_status": feature.get("displayStatus"), "retailer_code": feature.get("pickupStatus"), "earliest": (feature.get("fulfillmentTime") or {}).get("earliest")}
        products.extend({"product_id": pid, **by_id.get(pid, {"status": "unknown", "retailer_status": None, "retailer_code": None, "earliest": None})} for pid in batch)
    return {"retailer": self.retailer, "country": self.country, "language": self.language, "store_id": store_id, "products": products, "count": len(products), "checked_at": datetime.now(timezone.utc).isoformat()}

