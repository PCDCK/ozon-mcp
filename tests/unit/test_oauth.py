"""PerformanceTokenManager tests with mocked HTTP."""

from __future__ import annotations

import pytest

from ozon_mcp.errors import OzonAuthError
from ozon_mcp.transport.oauth import PerformanceTokenManager


async def test_token_fetch_caches(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api-performance.ozon.ru/api/client/token",
        method="POST",
        json={"access_token": "tok-1", "expires_in": 1800},
        status_code=200,
    )
    mgr = PerformanceTokenManager("client", "secret")
    assert await mgr.get_token() == "tok-1"
    # Second call uses cache, no extra HTTP request expected.
    assert await mgr.get_token() == "tok-1"
    assert len(httpx_mock.get_requests()) == 1


async def test_token_refresh_after_invalidate(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api-performance.ozon.ru/api/client/token",
        method="POST",
        json={"access_token": "tok-a", "expires_in": 1800},
        status_code=200,
    )
    httpx_mock.add_response(
        url="https://api-performance.ozon.ru/api/client/token",
        method="POST",
        json={"access_token": "tok-b", "expires_in": 1800},
        status_code=200,
    )
    mgr = PerformanceTokenManager("c", "s")
    assert await mgr.get_token() == "tok-a"
    mgr.invalidate()
    assert await mgr.get_token() == "tok-b"


async def test_token_failure_raises_auth_error(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api-performance.ozon.ru/api/client/token",
        method="POST",
        json={"error": "invalid_client"},
        status_code=401,
    )
    mgr = PerformanceTokenManager("c", "s")
    with pytest.raises(OzonAuthError):
        await mgr.get_token()


def test_missing_credentials_raises_at_construction() -> None:
    with pytest.raises(OzonAuthError):
        PerformanceTokenManager("", "")
