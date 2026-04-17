"""Auto-extraction of enum values from Ozon's markdown bullet descriptions."""

from __future__ import annotations

from ozon_mcp.schema import load_catalog
from ozon_mcp.schema.extractor import (
    _extract_enum_values,
    enrich_enums_from_description,
)


def test_extracts_simple_bullet_list() -> None:
    desc = """
    Тип сортировки:
    - `asc` — по возрастанию,
    - `desc` — по убыванию,
    - `none` — без сортировки.
    """
    values = _extract_enum_values(desc)
    assert values == ["asc", "desc", "none"]


def test_extracts_camelcase_values() -> None:
    desc = """
    Способы группировки:
    - `unknownDimension` — неизвестное измерение,
    - `category1` — категория первого уровня,
    - `modelID` — модель.
    """
    values = _extract_enum_values(desc)
    assert "unknownDimension" in values
    assert "category1" in values
    assert "modelID" in values


def test_too_few_values_returns_none() -> None:
    desc = "Только два варианта: `a` и `b`."
    assert _extract_enum_values(desc) is None


def test_no_backticks_returns_none() -> None:
    desc = "Просто описание без enum значений."
    assert _extract_enum_values(desc) is None


def test_dedupes_values() -> None:
    desc = """
    - `foo` — один,
    - `bar` — два,
    - `foo` — повтор,
    - `baz` — три.
    """
    values = _extract_enum_values(desc)
    assert values == ["foo", "bar", "baz"]


def test_enriches_string_property_with_no_enum() -> None:
    schema = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Статусы:\n- `active` — активен,\n- `paused` — приостановлен,\n- `closed` — закрыт.",
            }
        },
    }
    enrich_enums_from_description(schema)
    assert schema["properties"]["status"]["enum"] == ["active", "paused", "closed"]
    assert schema["properties"]["status"]["x-enum-source"] == "description"


def test_enriches_array_of_string_property() -> None:
    schema = {
        "type": "array",
        "description": "Метрики:\n- `revenue` — выручка,\n- `units` — единицы,\n- `clicks` — клики.",
        "items": {"type": "string"},
    }
    enrich_enums_from_description(schema)
    # Enum should land on the items, not the array.
    assert "enum" in schema["items"]
    assert schema["items"]["enum"] == ["revenue", "units", "clicks"]


def test_does_not_overwrite_existing_enum() -> None:
    schema = {
        "type": "string",
        "description": "Виды:\n- `a` — один,\n- `b` — два,\n- `c` — три.",
        "enum": ["x", "y"],
    }
    enrich_enums_from_description(schema)
    # Existing enum is preserved as-is.
    assert schema["enum"] == ["x", "y"]
    assert "x-enum-source" not in schema


def test_analytics_dimension_enriched_in_catalog() -> None:
    """Regression: AnalyticsAPI_AnalyticsGetData dimension/metrics had
    enum: null in swagger but values listed in description text."""
    cat = load_catalog()
    m = cat.get_by_operation_id("AnalyticsAPI_AnalyticsGetData")
    assert m is not None
    assert m.request_schema is not None
    dim = m.request_schema["properties"]["dimension"]
    items = dim.get("items", {})
    enum = items.get("enum")
    assert enum is not None
    assert "day" in enum
    assert "week" in enum
    assert "month" in enum
    assert items.get("x-enum-source") == "description"


def test_at_least_50_methods_have_enriched_enums() -> None:
    """Sanity: enrichment should fire on dozens of fields across the catalog."""
    cat = load_catalog()
    enriched_count = 0

    def count(node):
        nonlocal enriched_count
        if isinstance(node, dict):
            if node.get("x-enum-source") == "description":
                enriched_count += 1
            for v in node.values():
                count(v)
        elif isinstance(node, list):
            for item in node:
                count(item)

    for m in cat.methods:
        if m.request_schema:
            count(m.request_schema)
        for s in m.response_schemas.values():
            count(s)

    assert enriched_count >= 50, f"only {enriched_count} fields enriched, expected ≥50"
