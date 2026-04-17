"""OAuth2 client_credentials token manager for Performance API.

The Performance API uses standard OAuth2 client_credentials grant. Tokens
expire after ~30 minutes. This manager fetches a token on demand, caches it
in memory until expiry-minus-margin, and refreshes safely under concurrent
requests via an asyncio.Lock with double-check pattern.

Security:
- The cached token lives only in process memory and never touches disk.
- On auth failure we surface only the HTTP status code, never the response
  body, so any token echoed by Ozon (unlikely but possible) does not leak.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx
import structlog

from ozon_mcp.errors import OzonAuthError

log = structlog.get_logger()

PERFORMANCE_AUTH_URL = "https://api-performance.ozon.ru/api/client/token"
REFRESH_MARGIN_SECONDS = 300


@dataclass
class CachedToken:
    access_token: str
    expires_at: float

    def is_valid(self) -> bool:
        return time.time() < (self.expires_at - REFRESH_MARGIN_SECONDS)


class PerformanceTokenManager:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        auth_url: str = PERFORMANCE_AUTH_URL,
        timeout: float = 15.0,
    ) -> None:
        if not client_id or not client_secret:
            raise OzonAuthError("performance credentials missing")
        self._client_id = client_id
        self._client_secret = client_secret
        self._auth_url = auth_url
        self._timeout = timeout
        self._cached: CachedToken | None = None
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        if self._cached and self._cached.is_valid():
            return self._cached.access_token
        async with self._lock:
            if self._cached and self._cached.is_valid():
                return self._cached.access_token
            self._cached = await self._fetch()
            return self._cached.access_token

    async def _fetch(self) -> CachedToken:
        log.info("performance_token_refresh")
        async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
            response = await client.post(
                self._auth_url,
                json={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
            )
        if response.status_code != 200:
            # Do NOT include response.text — it may echo credentials.
            raise OzonAuthError(
                f"performance token request failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )
        try:
            data = response.json()
        except ValueError as e:
            raise OzonAuthError("performance token response was not JSON") from e
        if not isinstance(data, dict):
            raise OzonAuthError("performance token response had unexpected shape")
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OzonAuthError("performance token response missing access_token")
        try:
            expires_in = float(data.get("expires_in", 1800))
        except (TypeError, ValueError):
            expires_in = 1800.0
        return CachedToken(
            access_token=access_token,
            expires_at=time.time() + expires_in,
        )

    def invalidate(self) -> None:
        self._cached = None
