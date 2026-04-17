"""Integration tests for ``ozon_search_methods`` MCP tool."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from ozon_mcp.server import create_server


@pytest.fixture(scope="module")
def server() -> Any:
    saved = {
        k: os.environ.pop(k, None)
        for k in (
            "OZON_CLIENT_ID",
            "OZON_API_KEY",
            "OZON_PERFORMANCE_CLIENT_ID",
            "OZON_PERFORMANCE_CLIENT_SECRET",
        )
    }
    try:
        return create_server()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def _parse(call_result: Any) -> dict[str, Any]:
    content_list = call_result[0]
    return json.loads(content_list[0].text)


async def test_search_russian_query_finds_product_methods(server: Any) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_search_methods",
            {"query": "товары", "limit": 10},
        )
    )
    assert result["count"] > 0
    assert any(
        "product" in r["path"].lower() or "товар" in r["section"].lower()
        for r in result["results"]
    )


async def test_search_english_query_finds_price_methods(server: Any) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_search_methods",
            {"query": "price", "limit": 10},
        )
    )
    assert result["count"] > 0
    assert any("price" in r["path"].lower() for r in result["results"])


async def test_search_empty_query_does_not_crash(server: Any) -> None:
    """An empty query must not raise — it returns either zero results or
    a sensible default. The contract is "no crash"."""
    result = _parse(
        await server.call_tool(
            "ozon_search_methods",
            {"query": "", "limit": 5},
        )
    )
    assert "count" in result
    assert isinstance(result["results"], list)


async def test_search_with_safety_filter(server: Any) -> None:
    """Filtering by safety='read' must not return any write/destructive
    methods in the result set."""
    result = _parse(
        await server.call_tool(
            "ozon_search_methods",
            {"query": "list", "safety": "read", "limit": 20},
        )
    )
    assert all(r["safety"] == "read" for r in result["results"])


async def test_search_with_api_filter(server: Any) -> None:
    """Filtering by api='performance' must only return Performance API
    methods."""
    result = _parse(
        await server.call_tool(
            "ozon_search_methods",
            {"query": "campaign", "api": "performance", "limit": 10},
        )
    )
    assert all(r["api"] == "performance" for r in result["results"])
    assert result["count"] > 0
