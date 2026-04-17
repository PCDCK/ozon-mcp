"""Live smoke tests against the real Ozon API.

These tests are skipped by default and require real credentials in env:

    OZON_CLIENT_ID, OZON_API_KEY  (Seller API)
    OZON_PERFORMANCE_CLIENT_ID, OZON_PERFORMANCE_CLIENT_SECRET  (Performance API)

Run only when you explicitly want to verify against production:

    uv run pytest tests/live -m live --no-header

Each test calls a read-only endpoint and checks the response shape, not the
data itself. Designed to fail loudly if Ozon changes the API or breaks auth.
"""

from __future__ import annotations

import pytest

from ozon_mcp.config import Config
from ozon_mcp.knowledge import load_knowledge
from ozon_mcp.transport.oauth import PerformanceTokenManager
from ozon_mcp.transport.performance import PerformanceClient
from ozon_mcp.transport.ratelimit import RateLimitRegistry
from ozon_mcp.transport.seller import SellerClient

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def config() -> Config:
    return Config()


@pytest.fixture(scope="module")
def rate_limits() -> RateLimitRegistry:
    return RateLimitRegistry(load_knowledge())


@pytest.fixture
async def seller_client(config: Config, rate_limits: RateLimitRegistry):
    if not config.has_seller_credentials():
        pytest.skip("OZON_CLIENT_ID / OZON_API_KEY not set")
    client = SellerClient(
        config.seller_client_id(),
        config.seller_api_key(),
        rate_limits=rate_limits,
    )
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def performance_client(config: Config, rate_limits: RateLimitRegistry):
    if not config.has_performance_credentials():
        pytest.skip("OZON_PERFORMANCE_CLIENT_ID / OZON_PERFORMANCE_CLIENT_SECRET not set")
    tm = PerformanceTokenManager(
        config.perf_client_id(),
        config.perf_client_secret(),
    )
    client = PerformanceClient(tm, rate_limits=rate_limits)
    try:
        yield client
    finally:
        await client.aclose()


async def test_seller_company_info(seller_client: SellerClient) -> None:
    """Trivial read-only call to confirm headers + auth work."""
    response = await seller_client.request(
        "POST",
        "/v1/seller/info",
        json_body={},
        operation_id="SellerAPI_SellerInfo",
    )
    assert isinstance(response, dict)


async def test_performance_token_acquired(performance_client: PerformanceClient) -> None:
    """Verify OAuth flow by hitting any endpoint that needs Bearer."""
    headers = await performance_client._auth_headers()
    assert headers["Authorization"].startswith("Bearer ")
