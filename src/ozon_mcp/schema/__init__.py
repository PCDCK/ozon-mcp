"""OpenAPI → JSON Schema engine — the core of ozon-mcp.

Public surface:
    Method        — pydantic model representing one Ozon API method
    Catalog       — in-memory index of all methods
    SearchIndex   — BM25 search over the catalog
    load_catalog  — factory that builds Catalog from bundled swagger files
"""

from ozon_mcp.schema.catalog import Catalog, load_catalog
from ozon_mcp.schema.extractor import Method
from ozon_mcp.schema.graph import MethodGraph
from ozon_mcp.schema.search import SearchIndex, SearchResult

__all__ = [
    "Catalog",
    "Method",
    "MethodGraph",
    "SearchIndex",
    "SearchResult",
    "load_catalog",
]
