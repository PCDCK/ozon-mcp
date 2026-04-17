"""Validate that anonymized fixtures parse cleanly into the typed
response models in ``schema/responses.py``."""

from __future__ import annotations

from ozon_mcp.schema.responses import (
    PricesResponse,
    ProductInfoResponse,
    ProductListResponse,
    RatingSummaryResponse,
    SellerInfoResponse,
    TurnoverResponse,
    WarehouseListResponse,
)
from tests.fixtures import load_response


def test_product_list_fixture_parses() -> None:
    parsed = ProductListResponse(**load_response("product_list"))
    assert parsed.result.total == 3
    assert len(parsed.result.items) == 3
    assert parsed.result.items[0].product_id == 99000001
    assert parsed.result.items[2].archived is True


def test_product_info_fixture_parses() -> None:
    parsed = ProductInfoResponse(**load_response("product_info"))
    assert len(parsed.items) == 2
    item = parsed.items[0]
    assert item.id == 99000001
    assert item.name == "Test product 1"
    assert item.stocks is not None
    assert item.stocks.stocks[0].present == 12


def test_prices_fixture_parses() -> None:
    parsed = PricesResponse(**load_response("prices"))
    assert parsed.total == 2
    assert parsed.items[0].price.price == "399.0000"
    assert parsed.items[0].price_indexes is not None
    assert parsed.items[0].price_indexes.ozon_index_data is not None
    assert parsed.items[0].price_indexes.ozon_index_data.price_index_value == 1.01


def test_turnover_fixture_parses() -> None:
    parsed = TurnoverResponse(**load_response("turnover"))
    assert len(parsed.items) == 3
    assert parsed.items[0].turnover_grade == "DEFICIT"
    assert parsed.items[2].turnover_grade == "NO_SALES"


def test_seller_info_fixture_parses() -> None:
    parsed = SellerInfoResponse(**load_response("seller_info"))
    assert parsed.subscription is not None
    assert parsed.subscription.type == "PREMIUM_PLUS"
    assert parsed.subscription.is_premium is True


def test_rating_summary_fixture_parses() -> None:
    parsed = RatingSummaryResponse(**load_response("rating_summary"))
    assert len(parsed.groups) == 2
    assert parsed.groups[0].items[0].rating == "rating_on_time"
    assert parsed.groups[0].items[0].current_value == 97.5


def test_warehouse_list_fixture_parses() -> None:
    parsed = WarehouseListResponse(**load_response("warehouse_list"))
    assert len(parsed.result) == 1
    assert parsed.result[0].warehouse_id == 99100001
    assert parsed.result[0].is_rfbs is False


def test_extra_fields_pass_through() -> None:
    """Models tolerate Ozon adding new fields without breaking."""
    fixture = load_response("seller_info")
    fixture["new_field_ozon_invented_yesterday"] = "wat"
    parsed = SellerInfoResponse(**fixture)
    assert parsed.new_field_ozon_invented_yesterday == "wat"
