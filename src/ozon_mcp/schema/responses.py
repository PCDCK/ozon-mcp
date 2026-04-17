"""Pydantic models for the most heavily-used Ozon API responses.

These mirror the response shapes of the methods we sync most often
(product list, product info, prices, turnover, seller info, rating
summary). They are NOT used for production parsing — Ozon adds optional
fields fairly often and we do not want to break the sync on field drift.
Their purpose is:

    * Strong types for tests (``expected = ProductListResponse(**fixture)``)
    * Documentation of the shape we depend on
    * A hook for future strict deserialisation if we ever opt-in

All models declare ``extra="allow"`` for forward-compatibility with new
Ozon fields, and use ``ConfigDict(populate_by_name=True)`` so we can
freely alias fields if Ozon renames them.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _OzonModel(BaseModel):
    """Common config for all Ozon response models."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ---------------------------------------------------------- ProductAPI / list

class ProductListItem(_OzonModel):
    product_id: int
    offer_id: str
    archived: bool = False
    has_fbo_stocks: bool | None = None
    has_fbs_stocks: bool | None = None
    is_discounted: bool | None = None


class ProductListResult(_OzonModel):
    items: list[ProductListItem] = Field(default_factory=list)
    total: int | None = None
    last_id: str | None = None


class ProductListResponse(_OzonModel):
    """Response for ``/v3/product/list`` (`ProductAPI_GetProductList`)."""

    result: ProductListResult


# --------------------------------------------------- ProductAPI / info / list

class ProductStockEntry(_OzonModel):
    type: str  # "fbo" | "fbs"
    present: int
    reserved: int


class ProductStocks(_OzonModel):
    has_stock: bool | None = None
    stocks: list[ProductStockEntry] = Field(default_factory=list)


class ProductStatuses(_OzonModel):
    status: str | None = None
    moderate_status: str | None = None
    validation_status: str | None = None
    status_name: str | None = None
    is_created: bool | None = None
    status_updated_at: str | None = None


class ProductInfoItem(_OzonModel):
    id: int
    name: str
    offer_id: str
    barcode: str | None = None
    barcodes: list[str] = Field(default_factory=list)
    description_category_id: int | None = None
    type_id: int | None = None
    currency_code: str | None = None
    price: str | None = None
    old_price: str | None = None
    min_price: str | None = None
    marketing_price: str | None = None
    vat: str | None = None
    images: list[str] = Field(default_factory=list)
    primary_image: str | None = None
    statuses: ProductStatuses | None = None
    stocks: ProductStocks | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProductInfoResponse(_OzonModel):
    """Response for ``/v3/product/info/list`` (`ProductAPI_GetProductInfoList`)."""

    items: list[ProductInfoItem] = Field(default_factory=list)


# -------------------------------------------------- ProductAPI / info / prices

class PriceData(_OzonModel):
    currency_code: str | None = None
    price: str | None = None
    old_price: str | None = None
    min_price: str | None = None
    marketing_price: str | None = None
    marketing_seller_price: str | None = None
    vat: str | None = None
    auto_action_enabled: str | None = None


class PriceIndexBucket(_OzonModel):
    minimal_price: str | None = None
    minimal_price_currency: str | None = None
    price_index_value: float | None = None


class PriceIndexes(_OzonModel):
    color_index: str | None = None
    external_index_data: PriceIndexBucket | None = None
    ozon_index_data: PriceIndexBucket | None = None
    self_marketplaces_index_data: PriceIndexBucket | None = None


class PricesItem(_OzonModel):
    product_id: int
    offer_id: str
    price: PriceData
    price_indexes: PriceIndexes | None = None
    commissions: dict[str, Any] = Field(default_factory=dict)
    volume_weight: float | None = None
    acquiring: float | None = None


class PricesResponse(_OzonModel):
    """Response for ``/v5/product/info/prices`` (`ProductAPI_GetProductInfoPrices`)."""

    items: list[PricesItem] = Field(default_factory=list)
    total: int | None = None
    cursor: str | None = None


# --------------------------------------------------- AnalyticsAPI / turnover

class TurnoverItem(_OzonModel):
    sku: int
    name: str | None = None
    offer_id: str | None = None
    current_stock: int = 0
    ads: float | None = Field(default=None, description="Average daily sales")
    idc: float | None = Field(default=None, description="Inventory days cover")
    turnover_grade: str | None = None
    turnover_grade_cluster: str | None = None


class TurnoverResponse(_OzonModel):
    """Response for ``/v1/analytics/turnover/stocks``
    (`AnalyticsAPI_StocksTurnover`)."""

    items: list[TurnoverItem] = Field(default_factory=list)


# ------------------------------------------------------------ Seller / info

class SellerCompany(_OzonModel):
    name: str | None = None
    type: str | None = None


class SellerSubscription(_OzonModel):
    type: str | None = None
    is_premium: bool | None = None
    valid_until: str | None = None


class SellerInfoResponse(_OzonModel):
    """Response for ``/v1/seller/info`` (`SellerAPI_SellerInfo`)."""

    name: str | None = None
    company: SellerCompany | None = None
    subscription: SellerSubscription | None = None


# --------------------------------------------------------- Rating / summary

class RatingItem(_OzonModel):
    rating: str
    name: str | None = None
    current_value: float | int | None = None
    rating_direction: str | None = None
    status: str | None = None
    value_type: str | None = None


class RatingGroup(_OzonModel):
    group_name: str
    items: list[RatingItem] = Field(default_factory=list)


class PremiumScore(_OzonModel):
    rating: str
    value: float | int | None = None
    penalty_score_per_day: float | int | None = None
    scope: str | None = None


class RatingSummaryResponse(_OzonModel):
    """Response for ``/v1/rating/summary`` (`RatingAPI_RatingSummaryV1`)."""

    groups: list[RatingGroup] = Field(default_factory=list)
    premium_scores: list[PremiumScore] = Field(default_factory=list)


# ------------------------------------------------------------ Warehouse / list

class WarehouseFirstMileType(_OzonModel):
    first_mile_is_changing: bool | None = None
    first_mile_type: str | None = None


class WarehouseItem(_OzonModel):
    warehouse_id: int
    name: str
    is_rfbs: bool | None = None
    is_able_to_set_price: bool | None = None
    has_postings_limit: bool | None = None
    is_economy: bool | None = None
    is_kgt: bool | None = None
    status: str | None = None
    working_days: list[str] = Field(default_factory=list)
    min_postings_limit: int | None = None
    postings_limit: int | None = None
    min_working_days: int | None = None
    is_karantin: bool | None = None
    can_print_act_in_advance: bool | None = None
    first_mile_type: WarehouseFirstMileType | None = None


class WarehouseListResponse(_OzonModel):
    """Response for ``/v1/warehouse/list`` (`WarehouseAPI_WarehouseList`)."""

    result: list[WarehouseItem] = Field(default_factory=list)


__all__ = [
    "PremiumScore",
    "PriceData",
    "PriceIndexBucket",
    "PriceIndexes",
    "PricesItem",
    "PricesResponse",
    "ProductInfoItem",
    "ProductInfoResponse",
    "ProductListItem",
    "ProductListResponse",
    "ProductListResult",
    "ProductStatuses",
    "ProductStockEntry",
    "ProductStocks",
    "RatingGroup",
    "RatingItem",
    "RatingSummaryResponse",
    "SellerCompany",
    "SellerInfoResponse",
    "SellerSubscription",
    "TurnoverItem",
    "TurnoverResponse",
    "WarehouseFirstMileType",
    "WarehouseItem",
    "WarehouseListResponse",
]
