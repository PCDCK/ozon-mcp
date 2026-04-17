"""Performance API client — OAuth2 Bearer auth via PerformanceTokenManager."""

from __future__ import annotations

from ozon_mcp.transport.base import BaseClient
from ozon_mcp.transport.oauth import PerformanceTokenManager
from ozon_mcp.transport.ratelimit import RateLimitRegistry


class PerformanceClient(BaseClient):
    base_url = "https://api-performance.ozon.ru"
    api_label = "performance"

    def __init__(
        self,
        token_manager: PerformanceTokenManager,
        *,
        rate_limits: RateLimitRegistry,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(rate_limits=rate_limits, timeout=timeout, max_retries=max_retries)
        self._tokens = token_manager

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._tokens.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
