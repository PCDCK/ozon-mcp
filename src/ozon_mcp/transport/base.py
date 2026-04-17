"""Shared async HTTP client base for Seller and Performance clients.

Security/correctness notes:
- Auth credentials live only in instance attributes; we never log headers.
- Logs go to stderr via structlog (MCP stdio protocol owns stdout).
- Error payloads from Ozon are passed back to the caller, but auth headers
  are not echoed by the API so credentials don't leak through OzonError.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ozon_mcp.errors import (
    OzonAuthError,
    OzonConflictError,
    OzonError,
    OzonForbiddenError,
    OzonNotFoundError,
    OzonRateLimitError,
    OzonServerError,
    OzonValidationError,
)
from ozon_mcp.transport.ratelimit import RateLimitRegistry

log = structlog.get_logger()


class BaseClient:
    base_url: str = ""
    api_label: str = ""

    def __init__(
        self,
        *,
        rate_limits: RateLimitRegistry,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_connections: int = 50,
        max_keepalive: int = 20,
    ) -> None:
        self._rate_limits = rate_limits
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            http2=False,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive,
                keepalive_expiry=30.0,
            ),
        )
        self._max_retries = max_retries

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> BaseClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        operation_id: str | None = None,
        section: str | None = None,
        with_retry: bool = True,
    ) -> dict[str, Any]:
        """Execute a single API call.

        ``with_retry=True`` (default) keeps the tenacity-based retry loop for
        backwards compatibility with sync code that calls the transport
        directly. The MCP execution layer passes ``with_retry=False`` and
        owns retry semantics itself (Retry-After header + structured
        rate_limit_exceeded responses).
        """
        headers = await self._auth_headers()
        limiter = self._rate_limits.for_call(self.api_label, operation_id, section)

        async def _do() -> dict[str, Any]:
            async with limiter:
                log.info(
                    "ozon_request",
                    api=self.api_label,
                    method=method,
                    path=path,
                    operation_id=operation_id,
                )
                try:
                    response = await self._client.request(
                        method, path, json=json_body, headers=headers
                    )
                except httpx.TimeoutException as e:
                    # Treat as retryable server-side issue.
                    raise OzonServerError(
                        f"network timeout: {e}",
                        operation_id=operation_id,
                    ) from e
                except httpx.ConnectError as e:
                    # DNS / TCP / TLS failure — retry, may be transient (Ozon
                    # has occasional Cloudflare hiccups under bursts).
                    raise OzonServerError(
                        f"connection error: {e}",
                        operation_id=operation_id,
                    ) from e
                except httpx.HTTPError as e:
                    # Catch-all for other httpx-level errors so the agent
                    # always gets a typed exception, never a raw httpx one.
                    raise OzonError(
                        f"transport error: {e}",
                        operation_id=operation_id,
                    ) from e
                self._raise_for_status(response, operation_id)
                if not response.content:
                    return {}
                try:
                    parsed: Any = response.json()
                except ValueError:
                    return {"_raw": response.text}
                # Defensive: only return dicts. Lists/scalars wrap in {"data": ...}.
                if isinstance(parsed, dict):
                    return parsed
                return {"data": parsed}

        if not with_retry:
            return await _do()

        # reraise=True → original OzonError subclass propagates after exhaustion.
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential_jitter(initial=1, max=20),
            retry=retry_if_exception_type((OzonRateLimitError, OzonServerError)),
            reraise=True,
        ):
            with attempt:
                return await _do()
        # Unreachable: AsyncRetrying with reraise=True either returns or raises.
        raise OzonError("retry loop exited without result", operation_id=operation_id)

    async def _auth_headers(self) -> dict[str, str]:
        return {}

    @staticmethod
    def _raise_for_status(response: httpx.Response, operation_id: str | None) -> None:
        if response.status_code < 400:
            return

        # Parse the body defensively. Ozon usually returns JSON dicts on errors,
        # but we must not crash if it returns a string, list, or empty body.
        try:
            parsed: Any = response.json()
        except ValueError:
            parsed = None

        message = _extract_error_message(parsed) or response.reason_phrase
        payload: dict[str, Any]
        if isinstance(parsed, dict):
            payload = parsed
        elif parsed is not None:
            payload = {"raw": parsed}
        else:
            payload = {"raw_text": response.text[:500]}

        kwargs: dict[str, Any] = {
            "status_code": response.status_code,
            "operation_id": operation_id,
            "payload": payload,
        }

        status = response.status_code
        if status == 400:
            raise OzonValidationError(message, **kwargs)
        if status == 401:
            raise OzonAuthError(message, **kwargs)
        if status == 403:
            raise OzonForbiddenError(message, **kwargs)
        if status == 404:
            raise OzonNotFoundError(message, **kwargs)
        if status == 409:
            raise OzonConflictError(message, **kwargs)
        if status == 429:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            raise OzonRateLimitError(message, retry_after=retry_after, **kwargs)
        if status >= 500:
            raise OzonServerError(message, **kwargs)
        raise OzonError(message, **kwargs)


def _parse_retry_after(header_value: str | None) -> float | None:
    """Parse a ``Retry-After`` header per RFC 7231 §7.1.3.

    Accepts either delta-seconds (``"60"``) or an HTTP-date
    (``"Wed, 21 Oct 2026 07:28:00 GMT"``). Returns the number of seconds
    the caller should wait, or ``None`` when the header is missing /
    unparseable. Negative deltas (e.g. an HTTP-date already in the past)
    are clamped to 0.
    """
    if not header_value:
        return None
    try:
        return max(0.0, float(header_value))
    except ValueError:
        pass
    from datetime import datetime
    from email.utils import parsedate_to_datetime
    try:
        when = parsedate_to_datetime(header_value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    delta = (when - datetime.now(tz=UTC)).total_seconds()
    return max(0.0, delta)


def _extract_error_message(parsed: Any) -> str | None:
    """Pull a human-readable message out of an Ozon error body, if possible.

    Ozon uses several shapes:
        {"message": "..."}
        {"error": {"message": "...", "code": "..."}}
        {"code": "...", "details": [{"description": "..."}]}
    Anything we can't decode → returns None and the caller falls back to the
    HTTP reason phrase.
    """
    if not isinstance(parsed, dict):
        return None
    msg = parsed.get("message")
    if isinstance(msg, str) and msg:
        return msg
    error = parsed.get("error")
    if isinstance(error, dict):
        nested = error.get("message")
        if isinstance(nested, str) and nested:
            return nested
    if isinstance(error, str) and error:
        return error
    details = parsed.get("details")
    if isinstance(details, list) and details:
        first = details[0]
        if isinstance(first, dict):
            d_msg = first.get("description") or first.get("message")
            if isinstance(d_msg, str) and d_msg:
                return d_msg
    return None
