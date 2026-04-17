"""End-to-end tests for ``ozon_call_method`` and ``ozon_fetch_all``.

Uses ``pytest_httpx`` to intercept all outbound HTTP, so no live Ozon
call is ever made even if credentials are present in the environment.
Fixtures live in ``tests/fixtures/responses/*.json`` and carry only
anonymized data.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from ozon_mcp.knowledge.loader import load_knowledge
from ozon_mcp.schema import load_catalog
from ozon_mcp.tools import execution
from ozon_mcp.transport.ratelimit import RateLimitRegistry
from ozon_mcp.transport.seller import SellerClient
from tests.fixtures import load_response


def _parse(call_result: Any) -> dict[str, Any]:
    content_list = call_result[0]
    return json.loads(content_list[0].text)


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace asyncio.sleep so retries don't slow tests down."""

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(execution.asyncio, "sleep", _instant)


def _make_mcp() -> tuple[FastMCP, SellerClient]:
    catalog = load_catalog()
    knowledge = load_knowledge()
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller = SellerClient("test-id", "test-key", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None, knowledge=knowledge)
    return mcp, seller


# --------------------------------------------------------------------- happy
async def test_call_method_returns_parsed_response(httpx_mock: Any) -> None:
    fixture = load_response("product_list")
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/product/list",
        method="POST",
        json=fixture,
        status_code=200,
    )
    mcp, seller = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "ProductAPI_GetProductList",
                "params": {"filter": {"visibility": "ALL"}, "limit": 100},
            },
        )
    )
    assert result["ok"] is True
    items = result["response"]["result"]["items"]
    assert len(items) == 3
    assert items[0]["product_id"] == 99000001
    await seller.aclose()


async def test_call_method_seller_info_fixture(httpx_mock: Any) -> None:
    fixture = load_response("seller_info")
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v1/seller/info",
        method="POST",
        json=fixture,
        status_code=200,
    )
    mcp, seller = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {"operation_id": "SellerAPI_SellerInfo", "params": {}},
        )
    )
    assert result["ok"] is True
    assert result["response"]["subscription"]["type"] == "PREMIUM_PLUS"
    await seller.aclose()


# --------------------------------------------------------------------- 429 retry
async def test_call_method_429_retries_and_succeeds(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/product/list",
        method="POST",
        json={"message": "throttled"},
        status_code=429,
        headers={"retry-after": "1"},
    )
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/product/list",
        method="POST",
        json=load_response("product_list"),
        status_code=200,
    )
    mcp, seller = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "ProductAPI_GetProductList",
                "params": {"filter": {"visibility": "ALL"}, "limit": 100},
            },
        )
    )
    assert result["ok"] is True
    assert len(httpx_mock.get_requests()) == 2
    await seller.aclose()


# --------------------------------------------------------------------- gate
async def test_subscription_gate_blocks_call_before_http(httpx_mock: Any) -> None:
    """ProductPricesDetails requires PREMIUM_PRO. With cabinet PREMIUM_PLUS
    the gate must refuse locally — zero HTTP requests must go out."""
    mcp, seller = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "ProductPricesDetails",
                "params": {"skus": [99000001]},
                "cabinet_tier": "PREMIUM_PLUS",
            },
        )
    )
    assert result["error"] == "subscription_gate"
    assert result["error_type"] == "subscription_gate"
    assert result["http_call_skipped"] is True
    assert len(httpx_mock.get_requests()) == 0
    await seller.aclose()


# --------------------------------------------------------------------- slow endpoint
async def test_slow_endpoint_uses_semaphore(monkeypatch: pytest.MonkeyPatch) -> None:
    """The /v1/analytics/turnover/stocks endpoint must be wrapped in a
    Semaphore(1) so two concurrent calls cannot run in parallel."""

    semaphore = execution._get_slow_semaphore("/v1/analytics/turnover/stocks")
    assert semaphore is not None
    assert semaphore._value == 1


# --------------------------------------------------------------------- pagination
async def test_fetch_all_paginates_three_pages(httpx_mock: Any) -> None:
    from ozon_mcp.knowledge import PaginationPattern

    page1 = {
        "result": {
            "operations": [{"operation_id": i} for i in range(10)],
            "page_count": 3,
            "row_count": 25,
        }
    }
    page2 = {
        "result": {
            "operations": [{"operation_id": i} for i in range(10, 20)],
            "page_count": 3,
            "row_count": 25,
        }
    }
    page3 = {
        "result": {
            "operations": [{"operation_id": i} for i in range(20, 25)],
            "page_count": 3,
            "row_count": 25,
        }
    }
    for body in (page1, page2, page3):
        httpx_mock.add_response(
            url="https://api-seller.ozon.ru/v3/finance/transaction/list",
            method="POST",
            json=body,
            status_code=200,
        )

    knowledge = load_knowledge()
    knowledge._pagination_by_op["FinanceAPI_FinanceTransactionListV3"] = PaginationPattern(  # type: ignore[attr-defined]
        operation_id="FinanceAPI_FinanceTransactionListV3",
        type="page_number",
        request_offset_field="page",
        request_limit_field="page_size",
        response_items_field="operations",
        response_total_field="page_count",
        default_limit=10,
        max_limit=10,
    )
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, load_catalog(), seller, None, knowledge=knowledge)

    result = _parse(
        await mcp.call_tool(
            "ozon_fetch_all",
            {
                "operation_id": "FinanceAPI_FinanceTransactionListV3",
                "params": {
                    "filter": {"date": {"from": "2026-01-01T00:00:00Z",
                                          "to": "2026-01-31T23:59:59Z"}},
                },
                "max_items": 1000,
            },
        )
    )
    assert result["ok"] is True
    assert result["pages_fetched"] == 3
    assert result["total_fetched"] == 25
    assert result["truncated"] is False
    await seller.aclose()


# --------------------------------------------------------------------- deprecated
async def test_describe_method_returns_deprecation_info() -> None:
    """A method present in deprecated_methods.yaml must surface its
    deprecation note in describe_method output."""
    from ozon_mcp.schema import MethodGraph
    from ozon_mcp.tools.discovery import _serialize_method

    catalog = load_catalog()
    graph = MethodGraph(catalog)
    knowledge = load_knowledge()

    if not knowledge.deprecated_methods:
        pytest.skip("no deprecated methods curated yet — assertion is vacuous")

    op_id = knowledge.deprecated_methods[0].operation_id
    method = catalog.get_by_operation_id(op_id)
    if method is None:
        pytest.skip(f"deprecated op {op_id!r} no longer in catalog")
    serialised = _serialize_method(method, graph, knowledge)
    assert serialised.get("deprecated") is True or "deprecation" in serialised
