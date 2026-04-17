"""Execution-layer retry semantics: 429 / 5xx / timeout handling.

The transport layer no longer auto-retries when called with
``with_retry=False`` (which is what the MCP execution layer does), so all
backoff/Retry-After logic is exercised here in tools/execution.py.
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


def _parse(call_result) -> dict[str, Any]:
    content_list = call_result[0]
    return json.loads(content_list[0].text)


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real sleeps so 429/5xx retries finish in milliseconds."""

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


async def test_429_then_success_recovers(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={"message": "slow down"},
        status_code=429,
        headers={"retry-after": "1"},
    )
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={"result": {"operations": [], "page_count": 0, "row_count": 0}},
        status_code=200,
    )
    mcp, seller = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "FinanceAPI_FinanceTransactionListV3",
                "params": {
                    "filter": {"date": {"from": "2026-01-01T00:00:00Z",
                                          "to": "2026-01-31T23:59:59Z"}},
                    "page": 1,
                    "page_size": 100,
                },
            },
        )
    )
    assert result["ok"] is True
    await seller.aclose()


async def test_429_exhausted_returns_rate_limit(httpx_mock) -> None:
    for _ in range(execution.MAX_RETRIES + 1):
        httpx_mock.add_response(
            url="https://api-seller.ozon.ru/v3/finance/transaction/list",
            method="POST",
            json={"message": "throttled"},
            status_code=429,
            headers={"retry-after": "1"},
        )
    mcp, seller = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "FinanceAPI_FinanceTransactionListV3",
                "params": {
                    "filter": {"date": {"from": "2026-01-01T00:00:00Z",
                                          "to": "2026-01-31T23:59:59Z"}},
                    "page": 1,
                    "page_size": 100,
                },
            },
        )
    )
    assert result["error_type"] == "rate_limit"
    assert result["retryable"] is True
    assert result["retry_after_seconds"] == 1
    assert "Rate limit hit" in result["message"]
    await seller.aclose()


async def test_500_retries_then_succeeds(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={"message": "boom"},
        status_code=500,
    )
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={"result": {"operations": [], "page_count": 0, "row_count": 0}},
        status_code=200,
    )
    mcp, seller = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "FinanceAPI_FinanceTransactionListV3",
                "params": {
                    "filter": {"date": {"from": "2026-01-01T00:00:00Z",
                                          "to": "2026-01-31T23:59:59Z"}},
                    "page": 1,
                    "page_size": 100,
                },
            },
        )
    )
    assert result["ok"] is True
    await seller.aclose()


async def test_timeout_exhausted_returns_timeout(httpx_mock) -> None:
    import httpx as httpx_mod

    for _ in range(execution.MAX_RETRIES + 1):
        httpx_mock.add_exception(
            httpx_mod.ReadTimeout("simulated"),
            url="https://api-seller.ozon.ru/v3/finance/transaction/list",
            method="POST",
        )
    mcp, seller = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "FinanceAPI_FinanceTransactionListV3",
                "params": {
                    "filter": {"date": {"from": "2026-01-01T00:00:00Z",
                                          "to": "2026-01-31T23:59:59Z"}},
                    "page": 1,
                    "page_size": 100,
                },
            },
        )
    )
    assert result["error_type"] == "timeout"
    assert result["retryable"] is True
    await seller.aclose()


async def test_retry_after_header_is_honoured(httpx_mock, monkeypatch) -> None:
    """The execution layer must read Retry-After from the 429 response."""
    sleeps: list[float] = []

    async def _record(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(execution.asyncio, "sleep", _record)

    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={"message": "slow"},
        status_code=429,
        headers={"retry-after": "7"},
    )
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={"result": {"operations": [], "page_count": 0, "row_count": 0}},
        status_code=200,
    )
    mcp, seller = _make_mcp()
    await mcp.call_tool(
        "ozon_call_method",
        {
            "operation_id": "FinanceAPI_FinanceTransactionListV3",
            "params": {
                "filter": {"date": {"from": "2026-01-01T00:00:00Z",
                                      "to": "2026-01-31T23:59:59Z"}},
                "page": 1,
                "page_size": 100,
            },
        },
    )
    # First non-zero sleep value must equal the Retry-After header (7).
    assert 7 in sleeps
    await seller.aclose()


async def test_400_does_not_retry(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={"message": "bad payload"},
        status_code=400,
    )
    mcp, seller = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "FinanceAPI_FinanceTransactionListV3",
                "params": {
                    "filter": {"date": {"from": "2026-01-01T00:00:00Z",
                                          "to": "2026-01-31T23:59:59Z"}},
                    "page": 1,
                    "page_size": 100,
                },
            },
        )
    )
    assert result["error_type"] == "invalid_params"
    assert result["retryable"] is False
    # Single request was made — no retries on 400.
    assert len(httpx_mock.get_requests()) == 1
    await seller.aclose()
