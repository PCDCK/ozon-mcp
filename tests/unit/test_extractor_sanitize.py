"""Sanitizer drops invalid JSON Schema metadata that Ozon's swagger emits."""

from __future__ import annotations

import jsonschema
from jsonschema import Draft202012Validator

from ozon_mcp.schema import load_catalog
from ozon_mcp.schema.extractor import sanitize_schema


def test_sanitize_drops_null_description() -> None:
    raw = {
        "type": "object",
        "properties": {
            "x": {"type": "string", "description": None},
        },
    }
    cleaned = sanitize_schema(raw)
    assert "description" not in cleaned["properties"]["x"]


def test_sanitize_drops_null_enum() -> None:
    raw = {
        "type": "array",
        "items": {"type": "string", "enum": None},
    }
    cleaned = sanitize_schema(raw)
    assert "enum" not in cleaned["items"]


def test_sanitize_preserves_legitimate_null_default() -> None:
    raw = {"type": "string", "default": None}
    cleaned = sanitize_schema(raw)
    # default: null is legal JSON Schema, must survive.
    assert cleaned["default"] is None


def test_sanitize_recurses_into_arrays() -> None:
    raw = {
        "oneOf": [
            {"type": "string", "description": None},
            {"type": "integer"},
        ]
    }
    cleaned = sanitize_schema(raw)
    assert "description" not in cleaned["oneOf"][0]


def test_extracted_schemas_pass_metaschema_check() -> None:
    """Every extracted request and response schema in the catalog must be valid
    JSON Schema 2020-12. This is the regression test for the audit finding
    that AnalyticsGetData had `enum: null` and FBO list had `description: null`."""
    cat = load_catalog()
    failures: list[str] = []
    for m in cat.methods:
        if m.request_schema:
            try:
                Draft202012Validator.check_schema(m.request_schema)
            except jsonschema.SchemaError as e:
                failures.append(f"{m.operation_id} REQUEST: {str(e.message)[:100]}")
        for code, schema in m.response_schemas.items():
            try:
                Draft202012Validator.check_schema(schema)
            except jsonschema.SchemaError as e:
                failures.append(f"{m.operation_id} RESPONSE {code}: {str(e.message)[:100]}")
    assert not failures, f"{len(failures)} schemas still invalid:\n" + "\n".join(failures[:20])


def test_analytics_get_data_request_schema_is_valid() -> None:
    """Specific regression: AnalyticsGetData had `enum: null` in 4 places."""
    cat = load_catalog()
    m = cat.get_by_operation_id("AnalyticsAPI_AnalyticsGetData")
    assert m is not None
    assert m.request_schema is not None
    Draft202012Validator.check_schema(m.request_schema)


def test_fbo_posting_list_response_schema_is_valid() -> None:
    """Specific regression: FBO list response had `description: null`."""
    cat = load_catalog()
    m = cat.get_by_operation_id("PostingAPI_GetFboPostingList")
    assert m is not None
    schema = m.response_schemas.get("200")
    assert schema is not None
    Draft202012Validator.check_schema(schema)
