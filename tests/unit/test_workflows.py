"""Workflow registry tests — count, category filter, content shape.

Phase 3 added 5 analytical workflows on top of the 8 sync pipelines,
plus a `category` field on Workflow and a category filter on
``ozon_list_workflows``.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ozon_mcp.knowledge.loader import load_knowledge
from ozon_mcp.tools import workflow


def _parse(call_result: Any) -> dict[str, Any]:
    content_list = call_result[0]
    return json.loads(content_list[0].text)


def _make_mcp() -> FastMCP:
    mcp = FastMCP("test")
    workflow.register(mcp, load_knowledge())
    return mcp


# ── catalogue size ────────────────────────────────────────────────────


async def test_list_workflows_has_at_least_six_entries() -> None:
    """Phase 3 spec required ≥6 workflows. We ship 13."""
    mcp = _make_mcp()
    result = _parse(await mcp.call_tool("ozon_list_workflows", {}))
    assert result["count"] >= 6
    assert result["total"] >= 6
    names = {w["name"] for w in result["workflows"]}
    assert "oos_risk_analysis" in names
    assert "cabinet_health_check" in names
    assert "content_audit" in names
    assert "pricing_analysis" in names
    assert "warehouse_stock_distribution" in names


async def test_list_workflows_categories_include_analytics_and_health() -> None:
    mcp = _make_mcp()
    result = _parse(await mcp.call_tool("ozon_list_workflows", {}))
    cats = set(result["categories"])
    assert {"analytics", "health", "content", "pricing"}.issubset(cats)


# ── category filter ───────────────────────────────────────────────────


async def test_list_workflows_filtered_by_analytics() -> None:
    mcp = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_list_workflows", {"category": "analytics"}
        )
    )
    assert result["filter_category"] == "analytics"
    assert result["count"] >= 1
    assert all(w["category"] == "analytics" for w in result["workflows"])
    names = {w["name"] for w in result["workflows"]}
    assert "oos_risk_analysis" in names


async def test_list_workflows_filter_is_case_insensitive() -> None:
    mcp = _make_mcp()
    upper = _parse(
        await mcp.call_tool("ozon_list_workflows", {"category": "HEALTH"})
    )
    lower = _parse(
        await mcp.call_tool("ozon_list_workflows", {"category": "health"})
    )
    assert upper["count"] == lower["count"] >= 1


async def test_list_workflows_unknown_category_returns_empty() -> None:
    mcp = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_list_workflows", {"category": "totally_made_up"}
        )
    )
    assert result["count"] == 0
    assert result["workflows"] == []


# ── get_workflow content ──────────────────────────────────────────────


async def test_get_workflow_oos_has_required_fields() -> None:
    mcp = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_get_workflow", {"name": "oos_risk_analysis"}
        )
    )
    assert result["name"] == "oos_risk_analysis"
    assert result["category"] == "analytics"
    assert "rate_limit_note" in result
    assert "interpret" in result
    assert result.get("when_to_use")
    assert result.get("common_mistakes")
    assert len(result["steps"]) >= 1
    assert result["steps"][0]["operation_id"] == "AnalyticsAPI_StocksTurnover"


async def test_get_workflow_health_check_lists_three_steps() -> None:
    mcp = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_get_workflow", {"name": "cabinet_health_check"}
        )
    )
    op_ids = [s["operation_id"] for s in result["steps"]]
    assert "RatingAPI_RatingSummaryV1" in op_ids
    assert "SellerAPI_SellerInfo" in op_ids
    assert "AverageDeliveryTimeSummary" in op_ids


async def test_get_workflow_unknown_returns_error_with_available() -> None:
    mcp = _make_mcp()
    result = _parse(
        await mcp.call_tool(
            "ozon_get_workflow", {"name": "definitely_not_a_real_one"}
        )
    )
    assert "error" in result
    assert "available" in result
    assert isinstance(result["available"], list)
    assert "oos_risk_analysis" in result["available"]
