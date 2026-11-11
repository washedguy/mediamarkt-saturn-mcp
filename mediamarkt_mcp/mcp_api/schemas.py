"""Typed MCP response schemas."""
from typing import Literal
from pydantic import BaseModel


class CacheInfo(BaseModel):
    hit: bool
    age_seconds: float
    ttl_seconds: int

class Observation(BaseModel):
    observed_at: str | None = None
    cache: CacheInfo | None = None

class Delivery(BaseModel):
    status: Literal["available", "unavailable", "partial", "preorder", "unknown"]
    preorder: bool | None = None
    is_preorder: bool | None = None
    retailer_status: str | None
    retailer_code: str | None
    earliest: str | None

class Product(BaseModel):
    id: str | None
    title: str | None
    brand: str | None
    price: float | None
    currency: str
    url: str | None
    delivery: Delivery
    preorder: bool | None = None
    is_preorder: bool | None = None
    variants: list["Variant"] | None = None
    marketplace_offers: list["Offer"] | None = None
    offers_coverage: str | None = None
    enrichment_error: str | None = None
    enrichment_error_code: str | None = None
    details_observed_at: str | None = None
    details_cache: CacheInfo | None = None

class Paging(BaseModel):
    current_page: int
    page_count: int | None
    max_page: int | None

class SearchResult(Observation):
    retailer: str
    country: str = "de"
    language: str = "de"
    query: str
    products: list[Product]
    count: int
    total_products: int | None
    page: int
    next_page: int | None
    paging: Paging
    source: str
    coverage: str
    redirected_url: str | None = None
    related_pages: list[str] | None = None
    local_filters: list[str] | None = None
    note: str | None = None

class Variant(BaseModel):
    product_id: str
    title: str | None
    variant_name: str | None
    variant_value: str | None
    url: str | None

class Offer(BaseModel):
    offer_id: str
    product_id: str | None
    seller_id: str | None
    seller_name: str | None
    seller_rating: float | None
    price: float | None
    currency: str | None
    shipping_cost: float | None
    condition: str | None
    delivery: Delivery
    is_best_offer: bool | None

class Image(BaseModel):
    url: str
    alt: str | None

class Rating(BaseModel):
    average: float | None
    count: int | None
    scale: int | float | None

class Feature(BaseModel):
    name: str
    value: str | int | float | bool | None
    unit: str | None

class FeatureGroup(BaseModel):
    group: str | None
    items: list[Feature]

class ProductDetails(Product):
    ean: str | None
    resolved_url: str
    variants: list[Variant]
    marketplace_offers: list[Offer]
    offers_coverage: str
    description: str | None
    description_marketing: str | None
    images: list[Image]
    rating: Rating
    categories: list[str]
    features: list[FeatureGroup]

class ProductResult(Observation):
    retailer: str
    country: str = "de"
    language: str = "de"
    reference: str
    found: bool
    product: ProductDetails | None
    reason: str | None

class Address(BaseModel):
    street: str | None
    house_number: str | None
    postal_code: str | None
    city: str | None
    country: str | None

class Position(BaseModel):
    latitude: float | None
    longitude: float | None

class Store(BaseModel):
    id: str
    name: str | None
    address: Address
    position: Position
    phone: str | None

class StoreResult(Observation):
    retailer: str
    country: str = "de"
    language: str = "de"
    query: str
    stores: list[Store]
    count: int

class PickupItem(BaseModel):
    product_id: str
    status: Literal["available", "unavailable", "partial", "preorder", "unknown"]
    retailer_status: str | None
    retailer_code: str | None
    earliest: str | None

class PickupResult(Observation):
    retailer: str
    country: str = "de"
    language: str = "de"
    store_id: str
    products: list[PickupItem]
    count: int
    checked_at: str

class Storefront(BaseModel):
    country: str
    retailer: str
    languages: list[str]
    default_language: str
    currency: str
    url: str
    delivery_filter_languages: list[str]

class StorefrontList(BaseModel):
    storefronts: list[Storefront]

