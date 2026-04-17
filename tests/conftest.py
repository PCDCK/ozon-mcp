"""Shared test fixtures."""

from __future__ import annotations

import pytest

from ozon_mcp.schema import Catalog, SearchIndex, load_catalog


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return load_catalog()


@pytest.fixture(scope="session")
def search_index(catalog: Catalog) -> SearchIndex:
    return SearchIndex(catalog)
