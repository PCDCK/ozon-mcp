"""Seller API client — Client-Id + Api-Key header auth."""

from __future__ import annotations

from ozon_mcp.transport.base import BaseClient
from ozon_mcp.transport.ratelimit import RateLimitRegistry


class SellerClient(BaseClient):
    base_url = "https://api-seller.ozon.ru"
    api_label = "seller"

    def __init__(
        self,
        client_id: str,
        api_key: str,
        *,
        rate_limits: RateLimitRegistry,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(rate_limits=rate_limits, timeout=timeout, max_retries=max_retries)
        self._client_id = client_id
        self._api_key = api_key

    async def _auth_headers(self) -> dict[str, str]:
        return {
            "Client-Id": self._client_id,
            "Api-Key": self._api_key,
            "Content-Type": "application/json",
        }
