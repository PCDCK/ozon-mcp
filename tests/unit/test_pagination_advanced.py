"""Cursor / last_id / page_token pagination edge cases.

Each test patches a synthetic ``PaginationPattern`` over the real
KnowledgeBase so we can drive the paginator with exact control over the
mocked Ozon responses (no need for the catalog method to actually have
that pattern in production).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from ozon_mcp.knowledge import PaginationPattern
from ozon_mcp.knowledge.loader import load_knowledge
from ozon_mcp.schema import load_catalog
from ozon_mcp.tools import execution
from ozon_mcp.transport.ratelimit import RateLimitRegistry
from ozon_mcp.transport.seller import SellerClient


def _parse(call_result: Any) -> dict[str, Any]:
    content_list = call_result[0]
    return json.loads(content_list[0].text)


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(execution.asyncio, "sleep", _instant)


def _patch_pattern(op_id: str, pattern: PaginationPattern):
    """Build an MCP server with the requested op_id forced to ``pattern``."""
    knowledge = load_knowledge()
    knowledge._pagination_by_op[op_id] = pattern  # type: ignore[attr-defined]
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, load_catalog(), seller, None, knowledge=knowledge)
    return mcp, seller


# ── cursor pagination ──────────────────────────────────────────────────


async def test_cursor_pagination_walks_two_pages(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v5/product/info/prices",
        method="POST",
        json={"items": [{"product_id": i} for i in range(10)],
              "cursor": "next-page", "total": 15},
        status_code=200,
    )
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v5/product/info/prices",
        method="POST",
        json={"items": [{"product_id": i} for i in range(10, 15)],
              "cursor": "", "total": 15},
        status_code=200,
    )
    mcp, seller = _patch_pattern(
        "ProductAPI_GetProductInfoPrices",
        PaginationPattern(
            operation_id="ProductAPI_GetProductInfoPrices",
            type="cursor",
            request_offset_field="cursor",
            request_limit_field="limit",
            response_items_field="items",
            response_total_field="cursor",
            default_limit=10,
            max_limit=10,
        ),
    )
    result = _parse(
        await mcp.call_tool(
            "ozon_fetch_all",
            {
                "operation_id": "ProductAPI_GetProductInfoPrices",
                "params": {"filter": {"visibility": "ALL"}},
                "max_items": 1000,
            },
        )
    )
    assert result["ok"] is True
    assert result["total_fetched"] == 15
    assert result["pages_fetched"] == 2
    await seller.aclose()


async def test_cursor_repeats_breaks_loop(httpx_mock: Any) -> None:
    """Server returns the same cursor twice — paginator must NOT loop forever."""
    for _ in range(2):
        httpx_mock.add_response(
            url="https://api-seller.ozon.ru/v5/product/info/prices",
            method="POST",
            json={"items": [{"product_id": i} for i in range(10)],
                  "cursor": "STUCK"},
            status_code=200,
        )
    mcp, seller = _patch_pattern(
        "ProductAPI_GetProductInfoPrices",
        PaginationPattern(
            operation_id="ProductAPI_GetProductInfoPrices",
            type="cursor",
            request_offset_field="cursor",
            request_limit_field="limit",
            response_items_field="items",
            response_total_field="cursor",
            default_limit=10,
            max_limit=10,
        ),
    )
    result = _parse(
        await mcp.call_tool(
            "ozon_fetch_all",
            {
                "operation_id": "ProductAPI_GetProductInfoPrices",
                "params": {"filter": {"visibility": "ALL"}},
                "max_items": 10000,
            },
        )
    )
    assert result["ok"] is True
    assert result["pages_fetched"] == 2
    assert result["total_fetched"] == 20
    assert len(httpx_mock.get_requests()) == 2
    await seller.aclose()


# ── last_id pagination ─────────────────────────────────────────────────


async def test_last_id_pagination_walks_two_pages(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/product/list",
        method="POST",
        json={"result": {
            "items": [{"product_id": i, "id": i} for i in range(10)],
            "last_id": "page1",
            "total": 15,
        }},
        status_code=200,
    )
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/product/list",
        method="POST",
        json={"result": {
            "items": [{"product_id": i, "id": i} for i in range(10, 15)],
            "last_id": "",
            "total": 15,
        }},
        status_code=200,
    )
    mcp, seller = _patch_pattern(
        "ProductAPI_GetProductList",
        PaginationPattern(
            operation_id="ProductAPI_GetProductList",
            type="last_id",
            request_offset_field="last_id",
            request_limit_field="limit",
            response_items_field="items",
            response_total_field="last_id",
            default_limit=10,
            max_limit=10,
        ),
    )
    result = _parse(
        await mcp.call_tool(
            "ozon_fetch_all",
            {
                "operation_id": "ProductAPI_GetProductList",
                "params": {"filter": {"visibility": "ALL"}},
                "max_items": 1000,
            },
        )
    )
    assert result["ok"] is True
    assert result["total_fetched"] == 15
    await seller.aclose()


async def test_last_id_repeats_breaks_loop(httpx_mock: Any) -> None:
    """Server returns the same last_id twice — must stop."""
    for _ in range(2):
        httpx_mock.add_response(
            url="https://api-seller.ozon.ru/v3/product/list",
            method="POST",
            json={"result": {
                "items": [{"product_id": i, "id": i} for i in range(10)],
                "last_id": "STUCK",
            }},
            status_code=200,
        )
    mcp, seller = _patch_pattern(
        "ProductAPI_GetProductList",
        PaginationPattern(
            operation_id="ProductAPI_GetProductList",
            type="last_id",
            request_offset_field="last_id",
            request_limit_field="limit",
            response_items_field="items",
            response_total_field="last_id",
            default_limit=10,
            max_limit=10,
        ),
    )
    result = _parse(
        await mcp.call_tool(
            "ozon_fetch_all",
            {"operation_id": "ProductAPI_GetProductList",
             "params": {}, "max_items": 1000},
        )
    )
    assert result["ok"] is True
    assert len(httpx_mock.get_requests()) == 2
    await seller.aclose()


# ── empty / total=0 / max_items validation ─────────────────────────────


async def test_first_page_empty_returns_no_items(httpx_mock: Any) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v5/product/info/prices",
        method="POST",
        json={"items": [], "cursor": "", "total": 0},
        status_code=200,
    )
    mcp, seller = _patch_pattern(
        "ProductAPI_GetProductInfoPrices",
        PaginationPattern(
            operation_id="ProductAPI_GetProductInfoPrices",
            type="cursor",
            request_offset_field="cursor",
            request_limit_field="limit",
            response_items_field="items",
            response_total_field="cursor",
            default_limit=10,
            max_limit=10,
        ),
    )
    result = _parse(
        await mcp.call_tool(
            "ozon_fetch_all",
            {"operation_id": "ProductAPI_GetProductInfoPrices",
             "params": {"filter": {"visibility": "ALL"}}, "max_items": 100},
        )
    )
    assert result["ok"] is True
    assert result["items"] == []
    assert result["pages_fetched"] == 1
    assert result["truncated"] is False
    await seller.aclose()


async def test_max_items_zero_is_rejected() -> None:
    knowledge = load_knowledge()
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, load_catalog(), seller, None, knowledge=knowledge)
    result = _parse(
        await mcp.call_tool(
            "ozon_fetch_all",
            {"operation_id": "ProductAPI_GetProductList", "max_items": 0},
        )
    )
    assert result["error_type"] == "invalid_params"
    assert "max_items" in result["message"]
    await seller.aclose()


async def test_max_items_above_cap_is_rejected() -> None:
    knowledge = load_knowledge()
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, load_catalog(), seller, None, knowledge=knowledge)
    result = _parse(
        await mcp.call_tool(
            "ozon_fetch_all",
            {"operation_id": "ProductAPI_GetProductList",
             "max_items": execution.MAX_FETCH_ALL_ITEMS + 1},
        )
    )
    assert result["error_type"] == "invalid_params"
    await seller.aclose()
