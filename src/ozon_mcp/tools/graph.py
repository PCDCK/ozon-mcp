"""Method relationship tool — exposes the auto-extracted method graph."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ozon_mcp.schema import Catalog, MethodGraph
from ozon_mcp.schema.errors import make_error


def register(mcp: FastMCP, catalog: Catalog, graph: MethodGraph) -> None:
    @mcp.tool()
    def ozon_get_related_methods(
        operation_id: str,
        max_hops: int = 1,
    ) -> dict[str, Any]:
        """Find methods related to a given one (auto-extracted from doc links + workflows).

        Returns methods that this operation links to in its description, plus
        methods that link back to it. Useful for understanding which calls
        you'll likely need together when integrating a feature.

        Args:
            operation_id: source method
            max_hops: 1 = direct neighbours, 2 = neighbours of neighbours
        """
        if catalog.get_by_operation_id(operation_id) is None:
            return make_error(
                "not_found",
                f"operation_id {operation_id!r} not found",
                operation_id=operation_id,
                error="NotFound",
            )
        related = graph.related(operation_id, max_hops=max_hops)
        return {
            "operation_id": operation_id,
            "max_hops": max_hops,
            "count": len(related),
            "methods": [
                {
                    "operation_id": m.operation_id,
                    "api": m.api,
                    "method": m.method,
                    "path": m.path,
                    "summary": m.summary,
                    "section": m.section,
                }
                for m in related
            ],
        }
