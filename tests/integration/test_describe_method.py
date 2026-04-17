"""Integration tests for ``ozon_describe_method`` MCP tool."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from ozon_mcp.server import create_server


@pytest.fixture(scope="module")
def server() -> Any:
    """Build the MCP server with all credentials wiped from env so the
    execution layer is disabled and no live call is ever attempted."""
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


async def test_describe_returns_required_fields(server: Any) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_describe_method",
            {"operation_id": "ProductAPI_GetProductList"},
        )
    )
    # Mandatory fields the contract promises.
    for field in (
        "operation_id", "api", "method", "path", "section",
        "summary", "description", "request_schema", "response_schemas",
    ):
        assert field in result, f"missing field {field!r} in describe output"
    assert result["operation_id"] == "ProductAPI_GetProductList"
    assert result["path"] == "/v3/product/list"
    assert result["api"] == "seller"


async def test_describe_includes_rate_limit_and_examples(server: Any) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_describe_method",
            {"operation_id": "FinanceAPI_FinanceTransactionListV3"},
        )
    )
    assert "rate_limit" in result
    assert result["rate_limit"]["per_minute"] is not None
    assert "quirks" in result
    assert "examples" in result


async def test_describe_subscription_block_with_required_and_source(
    server: Any,
) -> None:
    """For a curated subscription_overrides entry, the describe output
    must surface ``required`` and ``source`` so agents can pre-check."""
    result = _parse(
        await server.call_tool(
            "ozon_describe_method",
            {"operation_id": "ProductPricesDetails"},
        )
    )
    sub = result.get("subscription")
    assert sub is not None, "ProductPricesDetails has a curated subscription override"
    assert sub.get("required") == "PREMIUM_PRO"
    assert sub.get("source") in {"swagger", "empirical", "swagger+empirical",
                                   "swagger+curated", "curated"}


async def test_describe_unknown_operation_id_returns_not_found(server: Any) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_describe_method",
            {"operation_id": "TotallyMadeUpOperationDoesNotExist"},
        )
    )
    assert "error" in result


async def test_describe_deprecated_method_carries_deprecation_field(
    server: Any,
) -> None:
    """Deprecated methods carry either ``deprecated=True`` or a
    ``deprecation`` block — the loader handles both shapes."""
    from ozon_mcp.knowledge.loader import load_knowledge

    knowledge = load_knowledge()
    op = next(
        (m.operation_id for m in knowledge.deprecated_methods if m.operation_id),
        None,
    )
    if op is None:
        pytest.skip("no deprecated_methods.yaml entries to assert against")

    result = _parse(
        await server.call_tool(
            "ozon_describe_method",
            {"operation_id": op},
        )
    )
    assert result.get("deprecated") is True or "deprecation" in result
