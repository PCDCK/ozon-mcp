"""Direct tests for the $ref resolver."""

from __future__ import annotations

from ozon_mcp.schema.resolver import RefResolver


def test_resolves_simple_ref() -> None:
    spec = {
        "components": {
            "schemas": {
                "Foo": {"type": "object", "properties": {"x": {"type": "string"}}},
            },
        },
    }
    resolver = RefResolver(spec)
    out = resolver.resolve({"$ref": "#/components/schemas/Foo"})
    assert out == {"type": "object", "properties": {"x": {"type": "string"}}}


def test_resolves_nested_ref() -> None:
    spec = {
        "components": {
            "schemas": {
                "Inner": {"type": "string", "format": "date-time"},
                "Outer": {
                    "type": "object",
                    "properties": {"date": {"$ref": "#/components/schemas/Inner"}},
                },
            },
        },
    }
    resolver = RefResolver(spec)
    out = resolver.resolve({"$ref": "#/components/schemas/Outer"})
    assert out["properties"]["date"] == {"type": "string", "format": "date-time"}


def test_handles_cycle_without_recursion() -> None:
    spec = {
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "child": {"$ref": "#/components/schemas/Node"},
                    },
                },
            },
        },
    }
    resolver = RefResolver(spec)
    out = resolver.resolve({"$ref": "#/components/schemas/Node"})
    assert out["properties"]["value"] == {"type": "string"}
    # Cycle terminator must be a self-contained valid JSON Schema fragment.
    # Earlier we emitted `{"$ref": ...}` here, but consumers can't resolve
    # that — they don't ship the rest of the swagger doc.
    child = out["properties"]["child"]
    assert child["type"] == "object"
    assert child["x-cycle-ref"] == "Node"
    assert "$ref" not in child


def test_resolves_ref_at_request_body_level() -> None:
    spec = {
        "components": {
            "requestBodies": {
                "MyBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Foo"},
                        },
                    },
                },
            },
            "schemas": {
                "Foo": {"type": "object", "properties": {"x": {"type": "integer"}}},
            },
        },
    }
    resolver = RefResolver(spec)
    out = resolver.resolve({"$ref": "#/components/requestBodies/MyBody"})
    assert out["content"]["application/json"]["schema"] == {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
    }


def test_preserves_oneof_does_not_merge() -> None:
    spec = {
        "components": {
            "schemas": {
                "Filter": {
                    "oneOf": [
                        {"required": ["a"]},
                        {"required": ["b"]},
                    ],
                    "properties": {
                        "a": {"type": "string"},
                        "b": {"type": "string"},
                    },
                },
            },
        },
    }
    resolver = RefResolver(spec)
    out = resolver.resolve({"$ref": "#/components/schemas/Filter"})
    assert "oneOf" in out
    assert out["oneOf"] == [{"required": ["a"]}, {"required": ["b"]}]
    # Top-level should NOT have a merged required list.
    assert "required" not in out


def test_broken_ref_returns_valid_placeholder() -> None:
    """Broken refs (target doesn't exist) get replaced with a valid JSON
    Schema fragment so jsonschema validators don't crash."""
    resolver = RefResolver({"components": {"schemas": {}}})
    out = resolver.resolve({"$ref": "#/components/schemas/Missing"})
    assert out["type"] == "object"
    assert out["x-broken-ref"] == "Missing"
    assert "$ref" not in out
