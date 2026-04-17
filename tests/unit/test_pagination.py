"""ozon_fetch_all auto-pagination tests."""

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


def _parse(call_result) -> dict[str, Any]:
    content_list = call_result[0]
    return json.loads(content_list[0].text)


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(execution.asyncio, "sleep", _instant)


def _make_mcp() -> tuple[FastMCP, SellerClient]:
    catalog = load_catalog()
    knowledge = load_knowledge()
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None, knowledge=knowledge)
    return mcp, seller


def _page(items: list[dict], total: int) -> dict:
    return {
        "result": {"items": items, "total": total, "last_id": ""},
    }


async def test_fetch_all_page_number_walks_until_short_page(httpx_mock) -> None:
    """FinanceTransactionListV3 uses page_number — three pages of 10 each."""
    # Page 1: 10 items.
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={
            "result": {
                "operations": [{"operation_id": i} for i in range(10)],
                "page_count": 3,
                "row_count": 25,
            }
        },
        status_code=200,
    )
    # Page 2: 10 items.
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={
            "result": {
                "operations": [{"operation_id": i} for i in range(10, 20)],
                "page_count": 3,
                "row_count": 25,
            }
        },
        status_code=200,
    )
    # Page 3: 5 items (less than page_size → last page).
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={
            "result": {
                "operations": [{"operation_id": i} for i in range(20, 25)],
                "page_count": 3,
                "row_count": 25,
            }
        },
        status_code=200,
    )

    _, seller = _make_mcp()
    # Patch the pagination pattern to use 10 as default_limit so the
    # short last page (5) reliably ends the walk.
    from ozon_mcp.knowledge import KnowledgeBase, PaginationPattern

    monkey_pattern = PaginationPattern(
        operation_id="FinanceAPI_FinanceTransactionListV3",
        type="page_number",
        request_offset_field="page",
        request_limit_field="page_size",
        response_items_field="operations",
        response_total_field="page_count",
        default_limit=10,
        max_limit=10,
    )
    # Inject the pattern over what the YAML loader gave us so the page_size
    # math (10/page) lines up with the mocked response shape.
    knowledge: KnowledgeBase = load_knowledge()
    knowledge._pagination_by_op["FinanceAPI_FinanceTransactionListV3"] = monkey_pattern  # type: ignore[attr-defined]
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller2 = SellerClient("c", "k", rate_limits=rate_limits)
    mcp2 = FastMCP("test")
    execution.register(mcp2, load_catalog(), seller2, None, knowledge=knowledge)

    result = _parse(
        await mcp2.call_tool(
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
    assert result["total_fetched"] == 25
    assert result["truncated"] is False
    assert result["pages_fetched"] == 3
    assert len(result["items"]) == 25
    await seller.aclose()
    await seller2.aclose()


async def test_fetch_all_respects_max_items(httpx_mock) -> None:
    from ozon_mcp.knowledge import PaginationPattern

    # Two full pages of 10 — after page 2 we already have 20 ≥ max_items=15.
    for _ in range(2):
        httpx_mock.add_response(
            url="https://api-seller.ozon.ru/v3/finance/transaction/list",
            method="POST",
            json={
                "result": {
                    "operations": [{"operation_id": i} for i in range(10)],
                    "page_count": 5,
                    "row_count": 50,
                }
            },
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
                "max_items": 15,
            },
        )
    )
    assert result["ok"] is True
    assert result["truncated"] is True
    assert result["total_fetched"] == 15
    assert len(result["items"]) == 15
    await seller.aclose()


async def test_fetch_all_empty_last_page_ends_walk(httpx_mock) -> None:
    from ozon_mcp.knowledge import PaginationPattern

    # First call: full page. Second call: empty array → terminate.
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={
            "result": {
                "operations": [{"operation_id": i} for i in range(10)],
                "page_count": 2,
                "row_count": 10,
            }
        },
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

    # Only one mocked page returned 10 items; with default_limit=10 the
    # paginator now walks. To exit cleanly we add an empty page next.
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={
            "result": {
                "operations": [],
                "page_count": 1,
                "row_count": 10,
            }
        },
        status_code=200,
    )

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
    assert result["total_fetched"] == 10
    assert result["pages_fetched"] == 2
    assert result["truncated"] is False
    await seller.aclose()


async def test_fetch_all_rejects_non_paginated_method() -> None:
    knowledge = load_knowledge()
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, load_catalog(), seller, None, knowledge=knowledge)

    result = _parse(
        await mcp.call_tool(
            "ozon_fetch_all",
            {
                "operation_id": "SellerAPI_SellerInfo",
                "params": {},
            },
        )
    )
    assert result["error_type"] == "invalid_params"
    assert "no pagination pattern" in result["message"]
    await seller.aclose()
