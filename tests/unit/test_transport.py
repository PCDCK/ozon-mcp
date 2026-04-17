"""Mocked transport-layer tests — never hit real Ozon."""

from __future__ import annotations

import pytest

from ozon_mcp.errors import (
    OzonAuthError,
    OzonForbiddenError,
    OzonNotFoundError,
    OzonServerError,
    OzonValidationError,
)
from ozon_mcp.transport.ratelimit import RateLimitRegistry
from ozon_mcp.transport.seller import SellerClient


@pytest.fixture
def rate_limits() -> RateLimitRegistry:
    return RateLimitRegistry(kb=None)


async def test_seller_client_sets_auth_headers(httpx_mock, rate_limits) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v1/test",
        method="POST",
        json={"result": "ok"},
        status_code=200,
    )
    client = SellerClient("client-id-x", "api-key-y", rate_limits=rate_limits)
    response = await client.request("POST", "/v1/test", json_body={"a": 1})
    assert response == {"result": "ok"}
    request = httpx_mock.get_request()
    assert request.headers["Client-Id"] == "client-id-x"
    assert request.headers["Api-Key"] == "api-key-y"
    await client.aclose()


async def test_seller_client_400_raises_validation(httpx_mock, rate_limits) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v1/test",
        method="POST",
        json={"message": "bad param"},
        status_code=400,
    )
    client = SellerClient("c", "k", rate_limits=rate_limits)
    with pytest.raises(OzonValidationError) as exc:
        await client.request("POST", "/v1/test", json_body={})
    assert exc.value.status_code == 400
    await client.aclose()


async def test_seller_client_401_raises_auth(httpx_mock, rate_limits) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v1/test",
        method="POST",
        json={"message": "unauthorized"},
        status_code=401,
    )
    client = SellerClient("c", "k", rate_limits=rate_limits)
    with pytest.raises(OzonAuthError):
        await client.request("POST", "/v1/test", json_body={})
    await client.aclose()


async def test_seller_client_403_raises_forbidden(httpx_mock, rate_limits) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v1/test",
        method="POST",
        json={"message": "no premium"},
        status_code=403,
    )
    client = SellerClient("c", "k", rate_limits=rate_limits)
    with pytest.raises(OzonForbiddenError):
        await client.request("POST", "/v1/test", json_body={})
    await client.aclose()


async def test_seller_client_404_raises_not_found(httpx_mock, rate_limits) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v1/test",
        method="POST",
        json={"message": "missing"},
        status_code=404,
    )
    client = SellerClient("c", "k", rate_limits=rate_limits)
    with pytest.raises(OzonNotFoundError):
        await client.request("POST", "/v1/test", json_body={})
    await client.aclose()


async def test_seller_client_429_then_success(httpx_mock, rate_limits) -> None:
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v1/test",
        method="POST",
        json={"message": "slow down"},
        status_code=429,
        headers={"retry-after": "0"},
    )
    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v1/test",
        method="POST",
        json={"result": "ok"},
        status_code=200,
    )
    client = SellerClient("c", "k", rate_limits=rate_limits, max_retries=2)
    # The retry waits with jitter; tenacity wait_exponential_jitter(initial=1) sleeps ~1s.
    # That's tolerable in a unit test (one retry only).
    response = await client.request("POST", "/v1/test", json_body={})
    assert response == {"result": "ok"}
    await client.aclose()


async def test_seller_client_500_retries_then_raises(httpx_mock, rate_limits) -> None:
    for _ in range(3):
        httpx_mock.add_response(
            url="https://api-seller.ozon.ru/v1/test",
            method="POST",
            json={"message": "boom"},
            status_code=500,
        )
    client = SellerClient("c", "k", rate_limits=rate_limits, max_retries=3)
    with pytest.raises(OzonServerError):
        await client.request("POST", "/v1/test", json_body={})
    await client.aclose()


async def test_seller_client_connect_error_wrapped(httpx_mock, rate_limits) -> None:
    """httpx.ConnectError must be wrapped in OzonServerError so the agent
    never sees a raw httpx exception. The audit run on 2026-04-11 caught
    the original bug where ConnectError bubbled up unwrapped under burst load."""
    import httpx as httpx_mod

    httpx_mock.add_exception(
        httpx_mod.ConnectError("simulated connect failure"),
        url="https://api-seller.ozon.ru/v1/test",
        method="POST",
    )
    httpx_mock.add_exception(
        httpx_mod.ConnectError("simulated connect failure"),
        url="https://api-seller.ozon.ru/v1/test",
        method="POST",
    )
    httpx_mock.add_exception(
        httpx_mod.ConnectError("simulated connect failure"),
        url="https://api-seller.ozon.ru/v1/test",
        method="POST",
    )
    client = SellerClient("c", "k", rate_limits=rate_limits, max_retries=3)
    with pytest.raises(OzonServerError) as exc:
        await client.request("POST", "/v1/test", json_body={})
    assert "connection error" in exc.value.message
    await client.aclose()


async def test_seller_client_timeout_wrapped(httpx_mock, rate_limits) -> None:
    """httpx.TimeoutException must also be wrapped (and is retried)."""
    import httpx as httpx_mod

    for _ in range(3):
        httpx_mock.add_exception(
            httpx_mod.ReadTimeout("simulated read timeout"),
            url="https://api-seller.ozon.ru/v1/test",
            method="POST",
        )
    client = SellerClient("c", "k", rate_limits=rate_limits, max_retries=3)
    with pytest.raises(OzonServerError) as exc:
        await client.request("POST", "/v1/test", json_body={})
    assert "timeout" in exc.value.message.lower()
    await client.aclose()
