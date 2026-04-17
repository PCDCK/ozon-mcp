"""Method relationship graph extraction."""

from __future__ import annotations

from ozon_mcp.schema import Catalog, MethodGraph


def test_graph_built_for_all_methods(catalog: Catalog) -> None:
    g = MethodGraph(catalog)
    assert g.node_count == catalog.total_methods
    # Markdown links exist in real Ozon descriptions, so we expect non-zero edges.
    assert g.edge_count > 50


def test_related_methods_for_known_linker(catalog: Catalog) -> None:
    g = MethodGraph(catalog)
    related = g.related("PostingAPI_GetFbsPostingListV3")
    assert related, "FBS list should link to several other methods"
    op_ids = {m.operation_id for m in related}
    # FBS list links to /v1/warehouse/list and /v1/delivery-method/list per its description.
    assert any("Warehouse" in op_id for op_id in op_ids)


def test_workflow_edges_added(catalog: Catalog) -> None:
    g = MethodGraph(catalog)
    base_edges = g.edge_count
    g.add_workflow_edges(
        [
            [
                "PostingAPI_GetFbsPostingListV3",
                "PostingAPI_GetFbsPostingV3",
            ]
        ]
    )
    assert g.edge_count >= base_edges
    related = g.related("PostingAPI_GetFbsPostingListV3")
    assert any(m.operation_id == "PostingAPI_GetFbsPostingV3" for m in related)


def test_unknown_operation_returns_empty(catalog: Catalog) -> None:
    g = MethodGraph(catalog)
    assert g.related("DoesNotExist") == []
