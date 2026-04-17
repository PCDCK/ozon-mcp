"""End-to-end tests calling MCP tools through the server interface."""

from __future__ import annotations

import json

import pytest

from ozon_mcp.server import create_server


@pytest.fixture(scope="module")
def server():
    # Hard-disable execution layer in tests so no test ever risks a live call,
    # even when the developer's shell exports OZON_* credentials.
    import os

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


def _parse(call_result) -> dict:
    content_list = call_result[0]
    return json.loads(content_list[0].text)


async def test_list_sections(server) -> None:
    result = _parse(await server.call_tool("ozon_list_sections", {}))
    assert result["total_methods"] >= 400
    assert result["seller_sections"]
    assert result["performance_sections"]


async def test_search_methods_russian(server) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_search_methods", {"query": "транзакции", "limit": 5}
        )
    )
    assert result["count"] > 0
    assert any("transaction" in r["path"] or "finance" in r["path"] for r in result["results"])


async def test_describe_method_returns_rich_payload(server) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_describe_method",
            {"operation_id": "FinanceAPI_FinanceTransactionListV3"},
        )
    )
    assert result["request_schema"] is not None
    assert "rate_limit" in result
    assert "quirks" in result
    assert "examples" in result
    assert result["rate_limit"]["per_minute"] is not None


async def test_describe_method_oneof_preserved(server) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_describe_method",
            {"operation_id": "FinanceAPI_FinanceTransactionListV3"},
        )
    )
    filter_schema = result["request_schema"]["properties"]["filter"]
    assert "oneOf" in filter_schema
    assert len(filter_schema["oneOf"]) == 2


async def test_list_workflows(server) -> None:
    result = _parse(await server.call_tool("ozon_list_workflows", {}))
    assert result["count"] >= 3
    names = {w["name"] for w in result["workflows"]}
    assert "sync_orders_fbo" in names


async def test_get_workflow(server) -> None:
    result = _parse(
        await server.call_tool("ozon_get_workflow", {"name": "sync_orders_fbo"})
    )
    assert result["name"] == "sync_orders_fbo"
    assert result["steps"]
    assert result["recommended_db_schema"]


async def test_get_workflow_unknown(server) -> None:
    result = _parse(
        await server.call_tool("ozon_get_workflow", {"name": "nope"})
    )
    assert "error" in result
    assert "available" in result


async def test_get_related_methods(server) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_get_related_methods",
            {"operation_id": "PostingAPI_GetFbsPostingListV3"},
        )
    )
    assert result["count"] > 0
    assert all("operation_id" in m for m in result["methods"])


async def test_get_rate_limits_for_method(server) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_get_rate_limits",
            {"operation_id": "FinanceAPI_FinanceTransactionListV3"},
        )
    )
    assert result["rate_limit"] is not None


async def test_get_error_catalog_by_code(server) -> None:
    result = _parse(await server.call_tool("ozon_get_error_catalog", {"code": "429"}))
    assert result["count"] > 0
    assert all(e["code"] == "429" for e in result["errors"])


async def test_get_examples(server) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_get_examples",
            {"operation_id": "FinanceAPI_FinanceTransactionListV3"},
        )
    )
    assert result["count"] >= 1
    assert all("request" in e for e in result["examples"])


async def test_list_methods_for_subscription(server) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_list_methods_for_subscription",
            {"tier": "PREMIUM_PLUS"},
        )
    )
    assert result["count"] > 0
    assert all("PREMIUM_PLUS" in m["all_tiers_mentioned"] for m in result["methods"])


async def test_list_methods_for_subscription_invalid_tier(server) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_list_methods_for_subscription",
            {"tier": "made-up"},
        )
    )
    assert "error" in result
    assert "valid_tiers" in result


async def test_describe_method_includes_subscription_when_present(server) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_describe_method",
            {"operation_id": "AnalyticsAPI_AnalyticsGetData"},
        )
    )
    assert "subscription" in result
    assert "PREMIUM_PLUS" in result["subscription"]["tiers_mentioned"]


async def test_describe_method_no_subscription_block_when_none(server) -> None:
    result = _parse(
        await server.call_tool(
            "ozon_describe_method",
            {"operation_id": "AccessAPI_RolesByToken"},
        )
    )
    # Auth helper doesn't mention any Premium tier.
    assert "subscription" not in result
