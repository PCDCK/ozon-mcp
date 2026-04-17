"""Curated workflow tools — pre-baked recipes for common Ozon data pipelines."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ozon_mcp.knowledge import KnowledgeBase
from ozon_mcp.schema.errors import make_error


def register(mcp: FastMCP, kb: KnowledgeBase) -> None:
    @mcp.tool()
    def ozon_list_workflows(category: str | None = None) -> dict[str, Any]:
        """List all curated workflows, optionally filtered by category.

        Workflows are step-by-step recipes for chaining Ozon API methods into
        real data pipelines or analytical reports. Use ``ozon_get_workflow``
        to fetch the full plan for a specific workflow.

        Args:
            category: optional filter — one of "catalog", "orders",
                "analytics", "health", "pricing", "content", "advertising",
                "warehouse", "returns", "finance". When provided, only
                workflows in that category are returned. ``categories`` in
                the response always lists every value present in the catalogue.
        """
        all_workflows = kb.workflows
        categories = sorted({w.category for w in all_workflows if w.category})

        if category is not None:
            wanted = category.lower()
            filtered = [
                w for w in all_workflows
                if w.category is not None and w.category.lower() == wanted
            ]
        else:
            filtered = list(all_workflows)

        return {
            "count": len(filtered),
            "total": len(all_workflows),
            "categories": categories,
            "filter_category": category,
            "workflows": [
                {
                    "name": w.name,
                    "title": w.title,
                    "category": w.category,
                    "description": w.description.strip().split("\n")[0],
                    "step_count": len(w.steps),
                    "review_status": w.review_status,
                }
                for w in filtered
            ],
        }

    @mcp.tool()
    def ozon_get_workflow(name: str) -> dict[str, Any]:
        """Get the full step-by-step plan for one workflow.

        Returns ordered steps with operation_ids, pagination/batching/concurrency
        guidance, recommended DB schema, and known gotchas. Analytical
        workflows additionally carry ``interpret`` (how to read the data),
        ``when_to_use`` (situations the workflow fits) and ``common_mistakes``.

        Args:
            name: workflow name from ozon_list_workflows, e.g. "sync_orders_fbs"
                or "oos_risk_analysis"
        """
        wf = kb.get_workflow(name)
        if wf is None:
            return make_error(
                "not_found",
                f"workflow {name!r} not found",
                payload={"available": kb.list_workflow_names()},
                # Backwards-compat: existing tests/callers read top-level
                # `error` and `available`.
                error=f"workflow {name!r} not found",
                available=kb.list_workflow_names(),
            )
        return wf.model_dump(exclude_none=True)
