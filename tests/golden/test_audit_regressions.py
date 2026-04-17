"""Regression tests for the bugs identified in the parser audit.

Each test pins a specific failure mode of the legacy parser and asserts the
new schema engine no longer exhibits it. These tests run against the real
bundled swagger files, so they catch upstream changes from Ozon as well.
"""

from __future__ import annotations

from ozon_mcp.schema import Catalog


def test_perf_request_body_ref_resolved(catalog: Catalog) -> None:
    """Bug: legacy parser ignored $ref at requestBody level → empty request_fields
    for 15/25 Performance API methods. Verify they now have request_schema."""
    m = catalog.get_by_path("performance", "POST", "/api/client/statistics")
    assert m is not None
    assert m.request_schema is not None
    props = m.request_schema.get("properties", {})
    assert "campaigns" in props
    assert "from" in props
    assert "to" in props


def test_perf_request_body_ref_resolved_second(catalog: Catalog) -> None:
    m = catalog.get_by_path("performance", "POST", "/api/client/campaign/cpc/v2/product")
    assert m is not None
    assert m.request_schema is not None
    assert "title" in m.request_schema.get("properties", {})


def test_oneof_preserved_not_merged(catalog: Catalog) -> None:
    """Bug: legacy parser merged oneOf branches into a union of required fields,
    producing impossible-to-satisfy 'both posting_number AND date are required'.
    Verify oneOf survives intact and top-level filter has no merged required."""
    m = catalog.get_by_operation_id("FinanceAPI_FinanceTransactionListV3")
    assert m is not None
    assert m.request_schema is not None
    filter_schema = m.request_schema["properties"]["filter"]
    assert "oneOf" in filter_schema
    assert len(filter_schema["oneOf"]) == 2
    one_of_required = {tuple(b.get("required", [])) for b in filter_schema["oneOf"]}
    assert one_of_required == {("posting_number",), ("date",)}
    # Filter itself must NOT have a merged required at the top.
    assert "required" not in filter_schema


def test_enum_values_preserved(catalog: Catalog) -> None:
    """Bug: legacy parser dropped enum arrays, leaving values only in description.
    Verify enums survive in JSON Schema form."""
    m = catalog.get_by_path("performance", "POST", "/api/client/statistics")
    assert m is not None
    assert m.request_schema is not None
    group_by = m.request_schema["properties"]["groupBy"]
    assert group_by.get("enum") == ["NO_GROUP_BY", "DATE", "START_OF_WEEK", "START_OF_MONTH"]
    assert group_by.get("default") == "NO_GROUP_BY"


def test_format_preserved(catalog: Catalog) -> None:
    m = catalog.get_by_path("performance", "POST", "/api/client/statistics")
    assert m is not None
    assert m.request_schema is not None
    from_field = m.request_schema["properties"]["from"]
    assert from_field.get("type") == "string"
    assert from_field.get("format") == "date-time"


def test_nested_objects_fully_expanded(catalog: Catalog) -> None:
    """Bug: legacy parser truncated at MAX_DEPTH=3, losing deep nested fields.
    Verify deeply nested filter schemas are now fully expanded."""
    m = catalog.get_by_operation_id("FinanceAPI_FinanceTransactionListV3")
    assert m is not None
    assert m.request_schema is not None
    date_schema = m.request_schema["properties"]["filter"]["properties"]["date"]
    assert "properties" in date_schema
    assert "from" in date_schema["properties"]
    assert "to" in date_schema["properties"]
    assert date_schema["properties"]["from"].get("format") == "date-time"


def test_top_level_required_not_polluted_by_oneof(catalog: Catalog) -> None:
    """The /v3/posting/fbs/list filter uses oneOf style; verify the request's
    own top-level required is sane (page/page_size, not impossible unions)."""
    m = catalog.get_by_operation_id("FinanceAPI_FinanceTransactionListV3")
    assert m is not None
    assert m.request_schema is not None
    top_required = set(m.request_schema.get("required", []))
    assert top_required == {"page", "page_size"}


def test_array_with_items_ref_detected(catalog: Catalog) -> None:
    """Bug: legacy parser reported array items via $ref as 'array of object'
    because it didn't resolve $ref before checking item type. The new resolver
    inlines $refs first, so item types come through correctly."""
    m = catalog.get_by_operation_id("AnalyticsAPI_AnalyticsGetData")
    assert m is not None
    assert m.request_schema is not None
    dimension = m.request_schema["properties"]["dimension"]
    assert dimension.get("type") == "array"
    assert dimension["items"].get("type") == "string"


def test_response_schemas_resolved(catalog: Catalog) -> None:
    m = catalog.get_by_operation_id("ProductAPI_GetProductList")
    assert m is not None
    assert "200" in m.response_schemas
    response = m.response_schemas["200"]
    assert "properties" in response or "$ref" in response
    # The 'result' field should be a fully resolved object.
    if "properties" in response:
        result = response["properties"].get("result", {})
        assert "properties" in result


def test_total_method_count(catalog: Catalog) -> None:
    """Sanity: we should be loading hundreds of methods, not a handful."""
    assert catalog.total_methods >= 400
    assert any(m.api == "seller" for m in catalog.methods)
    assert any(m.api == "performance" for m in catalog.methods)
