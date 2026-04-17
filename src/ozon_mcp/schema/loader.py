"""Loads bundled OpenAPI 3.0 specs from package resources."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

SELLER_RESOURCE = "seller_swagger.json"
PERF_RESOURCE = "perf_swagger.json"


def load_spec(resource_name: str) -> dict[str, Any]:
    """Read a bundled swagger file and return parsed JSON."""
    data_pkg = files("ozon_mcp.data")
    text = (data_pkg / resource_name).read_text(encoding="utf-8")
    spec: dict[str, Any] = json.loads(text)
    if "paths" not in spec or "components" not in spec:
        raise ValueError(f"{resource_name}: missing required OpenAPI sections")
    return spec


def load_seller_spec() -> dict[str, Any]:
    return load_spec(SELLER_RESOURCE)


def load_perf_spec() -> dict[str, Any]:
    return load_spec(PERF_RESOURCE)
