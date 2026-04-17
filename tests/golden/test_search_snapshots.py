"""Snapshot-based regression test for the catalog search ranker.

Each entry in ``expected/search_results.json`` is the top-3 ``operation_id``
list for one fixture query, captured after the v0.6.0 reranking fixes. If
a change to the ranker shifts the top-3 for any query, this test fails so
the author can either update the snapshot (intentional improvement) or
revert the regression.

The snapshot covers the 14 query set used in the v0.6.0 search audit —
eight Russian and six English single-word queries spanning every top-level
seller domain (products, stocks, orders, pricing, ratings, warehouses,
turnover, promos).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ozon_mcp.knowledge import load_knowledge
from ozon_mcp.schema import Catalog, SearchIndex, load_catalog

_SNAPSHOT = Path(__file__).parent / "expected" / "search_results.json"
_EXPECTED: dict[str, list[str]] = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snapshot_search_index() -> SearchIndex:
    catalog: Catalog = load_catalog()
    knowledge = load_knowledge()
    # Same override policy as production server — see server.py.
    for override in knowledge.descriptions_overrides:
        method = catalog.get_by_operation_id(override.operation_id)
        if method is None:
            continue
        current = (method.description or "").strip()
        curated = override.description.strip()
        if not current or len(curated) > len(current):
            method.description = curated
    return SearchIndex(catalog)


@pytest.mark.parametrize(
    "query,expected_top3",
    list(_EXPECTED.items()),
    ids=list(_EXPECTED.keys()),
)
def test_search_snapshot(
    snapshot_search_index: SearchIndex,
    query: str,
    expected_top3: list[str],
) -> None:
    results = snapshot_search_index.search(query, limit=3)
    actual = [r.method.operation_id for r in results]
    assert actual == expected_top3, (
        f"Search regression for {query!r}:\n"
        f"  expected: {expected_top3}\n"
        f"  actual:   {actual}\n"
        f"If the change is intentional, regenerate "
        f"tests/golden/expected/search_results.json."
    )
