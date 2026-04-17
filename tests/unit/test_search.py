"""BM25 search behaviour."""

from __future__ import annotations

from ozon_mcp.schema import SearchIndex


def test_search_finds_finance_methods(search_index: SearchIndex) -> None:
    results = search_index.search("transaction", limit=5)
    assert results
    assert any("transaction" in r.method.path.lower() for r in results)


def test_search_supports_russian(search_index: SearchIndex) -> None:
    results = search_index.search("отправления", limit=5)
    assert results
    assert any("posting" in r.method.path.lower() for r in results)


def test_search_filter_by_api(search_index: SearchIndex) -> None:
    results = search_index.search("statistics", api="performance", limit=10)
    assert results
    for r in results:
        assert r.method.api == "performance"


def test_search_empty_query_returns_nothing(search_index: SearchIndex) -> None:
    assert search_index.search("") == []


def test_search_respects_limit(search_index: SearchIndex) -> None:
    results = search_index.search("product", limit=3)
    assert len(results) <= 3
