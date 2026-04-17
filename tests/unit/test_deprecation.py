"""Auto-detection of deprecated methods."""

from __future__ import annotations

from ozon_mcp.schema import Catalog, SearchIndex
from ozon_mcp.schema.extractor import _detect_deprecated


def test_detects_explicit_deprecated_flag() -> None:
    op = {"deprecated": True, "description": ""}
    is_dep, note = _detect_deprecated(op)
    assert is_dep
    assert note == "marked deprecated in OpenAPI spec"


def test_detects_russian_ustarevaet() -> None:
    op = {
        "description": "Метод устаревает и будет отключён 7 апреля 2026 года.",
        "summary": "Список складов",
    }
    is_dep, note = _detect_deprecated(op)
    assert is_dep
    assert note is not None
    assert "устарева" in note.lower()


def test_detects_obsolete_keyword() -> None:
    op = {"description": "This method is obsolete, use /v2/foo instead."}
    is_dep, _ = _detect_deprecated(op)
    assert is_dep


def test_detects_pereklyuchites_na() -> None:
    op = {"description": "Переключитесь на /v2/carriage/delivery/list."}
    is_dep, _ = _detect_deprecated(op)
    assert is_dep


def test_non_deprecated_returns_false() -> None:
    op = {"description": "Returns the list of orders."}
    is_dep, note = _detect_deprecated(op)
    assert not is_dep
    assert note is None


def test_catalog_finds_known_deprecated_methods(catalog: Catalog) -> None:
    """Regression: WarehouseAPI_WarehouseList must be flagged."""
    m = catalog.get_by_operation_id("WarehouseAPI_WarehouseList")
    assert m is not None
    assert m.deprecated
    assert m.deprecation_note is not None


def test_search_excludes_deprecated_by_default(
    catalog: Catalog, search_index: SearchIndex
) -> None:
    results = search_index.search("warehouse list", limit=10)
    op_ids = [r.method.operation_id for r in results]
    # WarehouseAPI_WarehouseList is deprecated → should not appear by default.
    assert "WarehouseAPI_WarehouseList" not in op_ids


def test_search_includes_deprecated_when_requested(
    catalog: Catalog, search_index: SearchIndex
) -> None:
    """With include_deprecated=True the deprecated methods appear in results,
    but ranked lower than working alternatives due to the 0.3x score penalty."""
    no_dep = search_index.search("WarehouseAPI_WarehouseList", limit=20)
    with_dep = search_index.search(
        "WarehouseAPI_WarehouseList", limit=20, include_deprecated=True
    )
    no_dep_ids = {r.method.operation_id for r in no_dep}
    with_dep_ids = {r.method.operation_id for r in with_dep}
    # The deprecated entry must appear only with the flag.
    assert "WarehouseAPI_WarehouseList" not in no_dep_ids
    assert "WarehouseAPI_WarehouseList" in with_dep_ids
