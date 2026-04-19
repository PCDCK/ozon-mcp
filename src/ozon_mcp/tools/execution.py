"""ozon_call_method + ozon_fetch_all — execute real Ozon API calls.

Registered only when credentials are present in env. Before hitting the
network it runs three layers of guardrails:

1. Safety class (read / write / destructive) — requires ``confirm_write``
   / ``i_understand_this_modifies_data`` for anything that mutates data.
2. Subscription gate — if the curated knowledge layer has a
   ``required_tier`` for the method and the cabinet tier is lower, we
   refuse the call locally and return a structured ``subscription_gate``
   error. Saves quota on calls that would 403 anyway.
3. JSON Schema validation — request body is validated against the
   method's resolved schema.

Errors are always returned as a structured dict (see ``schema/errors.py``).
Callers can distinguish missing-credentials / schema-mismatch /
subscription-gate / rate_limit / server / timeout cases programmatically.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import jsonschema
from mcp.server.fastmcp import FastMCP

from ozon_mcp import state
from ozon_mcp.errors import (
    OzonAuthError,
    OzonClientValidationError,
    OzonConflictError,
    OzonError,
    OzonForbiddenError,
    OzonNotFoundError,
    OzonRateLimitError,
    OzonServerError,
    OzonValidationError,
)
from ozon_mcp.knowledge import KnowledgeBase, PaginationPattern
from ozon_mcp.schema import Catalog
from ozon_mcp.schema.errors import OzonError as OzonErrorModel
from ozon_mcp.tools._safety import safe_tool
from ozon_mcp.transport.performance import PerformanceClient
from ozon_mcp.transport.seller import SellerClient

# Ascending order: every tier implicitly grants access to everything below it.
TIER_HIERARCHY: list[str] = [
    "LITE",
    "STANDARD",
    "PREMIUM",
    "PREMIUM_PLUS",
    "PREMIUM_PRO",
]

TIER_ALIASES: dict[str, str] = {
    "PREMIUM_LITE": "LITE",
}

# Retry policy applied at the execution layer (transport-level retry is
# disabled via with_retry=False so semantics are owned in one place).
MAX_RETRIES: int = 3
RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Hard cap on every backoff sleep, including Retry-After. Above this we'd
# rather return a structured rate_limit error than block the agent.
MAX_BACKOFF_SECONDS: int = 60

# Safety cap on ozon_fetch_all to keep an MCP call from runaway pagination.
MAX_FETCH_ALL_ITEMS: int = 100_000

# Slow endpoints with sub-1-RPS limits get a per-process semaphore so
# parallel callers can't trip Ozon's per-cabinet limiter. Confirmed live
# from ozon_sync_log on 2026-04-17 — see knowledge/rate_limits.yaml.
SLOW_ENDPOINTS: dict[str, asyncio.Semaphore] = {}
SLOW_ENDPOINT_MIN_DELAY: dict[str, float] = {
    "/v1/analytics/turnover/stocks": 60.0,
}

# Last-call timestamps per slow endpoint for inter-call pacing.
_SLOW_LAST_CALL: dict[str, float] = {}
_SLOW_LOCK: asyncio.Lock | None = None


def _get_slow_lock() -> asyncio.Lock:
    global _SLOW_LOCK
    if _SLOW_LOCK is None:
        _SLOW_LOCK = asyncio.Lock()
    return _SLOW_LOCK


def _get_slow_semaphore(path: str) -> asyncio.Semaphore | None:
    if path not in SLOW_ENDPOINT_MIN_DELAY:
        return None
    sem = SLOW_ENDPOINTS.get(path)
    if sem is None:
        sem = asyncio.Semaphore(1)
        SLOW_ENDPOINTS[path] = sem
    return sem


def _normalize_tier(tier: str | None) -> str | None:
    if tier is None:
        return None
    upper = tier.upper()
    return TIER_ALIASES.get(upper, upper)


def tier_sufficient(cabinet_tier: str | None, required_tier: str | None) -> bool:
    """Return True if ``cabinet_tier`` meets or exceeds ``required_tier``."""
    if required_tier is None or str(required_tier).lower() == "unknown":
        return True
    if cabinet_tier is None:
        return True
    cab = _normalize_tier(cabinet_tier)
    req = _normalize_tier(required_tier)
    if cab is None or req is None:
        return True
    try:
        return TIER_HIERARCHY.index(cab) >= TIER_HIERARCHY.index(req)
    except ValueError:
        return True


def _err(error_type: str, message: str, **fields: Any) -> dict[str, Any]:
    """Build a structured error envelope using the OzonError pydantic model."""
    return OzonErrorModel(
        error=fields.pop("error", error_type),
        error_type=error_type,  # type: ignore[arg-type]
        message=message,
        **fields,
    ).to_dict()


async def _execute_with_retry(
    request_func: Callable[[], Awaitable[dict[str, Any]]],
    *,
    operation_id: str,
    endpoint: str,
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """Run ``request_func`` with bounded retries on 429 / 5xx / timeout.

    Honours ``Retry-After`` when the upstream sends one; falls back to
    exponential backoff (1s, 2s, 4s) for the rest. Slow endpoints (see
    ``SLOW_ENDPOINTS``) are serialised via a semaphore plus a minimum
    inter-call delay enforced from this process.

    Returns either:
      * ``{"ok": True, "response": ...}`` on success
      * a structured OzonError dict on terminal failure
    """
    sem = _get_slow_semaphore(endpoint)
    if sem is not None:
        async with sem:
            await _slow_endpoint_pace(endpoint)
            return await _retry_loop(
                request_func,
                operation_id=operation_id,
                endpoint=endpoint,
                max_retries=max_retries,
            )
    return await _retry_loop(
        request_func,
        operation_id=operation_id,
        endpoint=endpoint,
        max_retries=max_retries,
    )


async def _slow_endpoint_pace(endpoint: str) -> None:
    """Sleep until at least ``MIN_DELAY`` has elapsed since the last call."""
    min_delay = SLOW_ENDPOINT_MIN_DELAY.get(endpoint)
    if not min_delay:
        return
    loop = asyncio.get_event_loop()
    async with _get_slow_lock():
        now = loop.time()
        last = _SLOW_LAST_CALL.get(endpoint)
        if last is not None:
            wait = (last + min_delay) - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = loop.time()
        _SLOW_LAST_CALL[endpoint] = now


async def _retry_loop(
    request_func: Callable[[], Awaitable[dict[str, Any]]],
    *,
    operation_id: str,
    endpoint: str,
    max_retries: int,
) -> dict[str, Any]:
    last_retry_after: int | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await request_func()
            return {"ok": True, "response": response}

        except OzonRateLimitError as e:
            retry_after_raw = e.retry_after if e.retry_after is not None else 60
            try:
                retry_after = int(float(retry_after_raw))
            except (TypeError, ValueError):
                retry_after = 60
            last_retry_after = retry_after
            if attempt < max_retries:
                await asyncio.sleep(min(retry_after, MAX_BACKOFF_SECONDS))
                continue
            return _err(
                "rate_limit",
                f"Rate limit hit after {max_retries} retries",
                code=429,
                status_code=429,
                operation_id=operation_id,
                endpoint=endpoint,
                retryable=True,
                retry_after_seconds=retry_after,
                payload=e.payload,
            )

        except OzonServerError as e:
            if "timeout" in (e.message or "").lower():
                last_exc_type: str = "timeout"
            else:
                last_exc_type = "server_error"
            if attempt < max_retries:
                await asyncio.sleep(min(2 ** attempt, MAX_BACKOFF_SECONDS))
                continue
            return _err(
                last_exc_type,
                e.message or "upstream server error",
                code=e.status_code,
                status_code=e.status_code,
                operation_id=operation_id,
                endpoint=endpoint,
                retryable=True,
                payload=e.payload,
            )

        except OzonAuthError as e:
            return _err(
                "auth",
                e.message,
                code=e.status_code,
                status_code=e.status_code,
                operation_id=operation_id,
                endpoint=endpoint,
                retryable=False,
                payload=e.payload,
            )
        except OzonForbiddenError as e:
            return _err(
                "forbidden",
                e.message,
                code=e.status_code,
                status_code=e.status_code,
                operation_id=operation_id,
                endpoint=endpoint,
                retryable=False,
                payload=e.payload,
            )
        except OzonNotFoundError as e:
            return _err(
                "not_found",
                e.message,
                code=e.status_code,
                status_code=e.status_code,
                operation_id=operation_id,
                endpoint=endpoint,
                retryable=False,
                payload=e.payload,
            )
        except OzonConflictError as e:
            return _err(
                "conflict",
                e.message,
                code=e.status_code,
                status_code=e.status_code,
                operation_id=operation_id,
                endpoint=endpoint,
                retryable=False,
                payload=e.payload,
            )
        except OzonValidationError as e:
            return _err(
                "invalid_params",
                e.message,
                code=e.status_code,
                status_code=e.status_code,
                operation_id=operation_id,
                endpoint=endpoint,
                retryable=False,
                payload=e.payload,
            )
        except OzonError as e:
            return _err(
                "unknown",
                e.message,
                code=e.status_code,
                status_code=e.status_code,
                operation_id=operation_id,
                endpoint=endpoint,
                retryable=False,
                payload=e.payload,
            )

    # Defensive: should be unreachable — every except above either returns or
    # continues the loop, and the loop terminates after max_retries+1 passes.
    return _err(
        "unknown",
        f"max retries ({max_retries}) exceeded",
        operation_id=operation_id,
        endpoint=endpoint,
        retryable=False,
        retry_after_seconds=last_retry_after,
    )


def register(
    mcp: FastMCP,
    catalog: Catalog,
    seller_client: SellerClient | None,
    performance_client: PerformanceClient | None,
    *,
    knowledge: KnowledgeBase | None = None,
) -> None:
    @mcp.tool()
    @safe_tool
    async def ozon_call_method(
        operation_id: str,
        params: dict[str, Any] | None = None,
        confirm_write: bool = False,
        i_understand_this_modifies_data: bool = False,
        cabinet_tier: str | None = None,
    ) -> dict[str, Any]:
        """Execute a real call against the Ozon API.

        SAFETY MODEL — read methods just work; write/destructive methods
        require explicit confirmation flags. Each method's safety class is
        visible in `ozon_describe_method` (`safety` field).

          - safety="read":        no flag needed
          - safety="write":       requires confirm_write=True
          - safety="destructive": requires BOTH confirm_write=True AND
                                  i_understand_this_modifies_data=True

        SUBSCRIPTION GATE — when the method requires a higher tariff than
        the current cabinet tier, the call is refused locally and no HTTP
        request is sent. Saves quota on calls that would 403 anyway.

        RATE LIMITS — 429 responses are retried up to MAX_RETRIES times
        honouring Retry-After. Slow endpoints (e.g. /v1/analytics/turnover/
        stocks at 1 req/min) are serialised via a per-process semaphore.

        On any failure returns a structured ``OzonError`` envelope —
        agents should inspect ``error_type`` and decide.

        Args:
            operation_id: e.g. "FinanceAPI_FinanceTransactionListV3"
            params: request body matching the method's request_schema
            confirm_write: required when method.safety == "write" or "destructive"
            i_understand_this_modifies_data: extra confirmation for destructive
            cabinet_tier: override the cached cabinet tier (e.g. "PREMIUM_PLUS")
        """
        return await _call_method(
            catalog=catalog,
            knowledge=knowledge,
            seller_client=seller_client,
            performance_client=performance_client,
            operation_id=operation_id,
            params=params,
            confirm_write=confirm_write,
            i_understand_this_modifies_data=i_understand_this_modifies_data,
            cabinet_tier=cabinet_tier,
        )

    @mcp.tool()
    @safe_tool
    async def ozon_fetch_all(
        operation_id: str,
        params: dict[str, Any] | None = None,
        max_items: int = 10000,
        cabinet_tier: str | None = None,
    ) -> dict[str, Any]:
        """Fetch all pages of a paginated Ozon endpoint.

        Walks the endpoint's pagination pattern (offset/page/last_id/cursor/
        page_token — see ``knowledge/pagination_patterns.yaml``) until the
        endpoint reports the last page or ``max_items`` is reached. Per-page
        rate limits are still enforced via the same machinery as
        ``ozon_call_method``.

        Args:
            operation_id: same as ozon_call_method, must support pagination
            params: request body WITHOUT offset/limit/last_id/cursor — the
                paginator owns those fields
            max_items: safety cap, range [1, MAX_FETCH_ALL_ITEMS]
            cabinet_tier: override the cached cabinet tier

        Returns:
            ``{"items": [...], "total_fetched": N, "truncated": bool,
              "pages_fetched": int}`` on success or a structured OzonError
            on failure.
        """
        if not isinstance(max_items, int) or max_items < 1:
            return _err(
                "invalid_params",
                f"max_items must be a positive integer, got {max_items!r}",
                operation_id=operation_id,
            )
        if max_items > MAX_FETCH_ALL_ITEMS:
            return _err(
                "invalid_params",
                (
                    f"max_items={max_items} exceeds safety cap "
                    f"{MAX_FETCH_ALL_ITEMS}; raise MAX_FETCH_ALL_ITEMS or "
                    f"split your query."
                ),
                operation_id=operation_id,
            )
        if knowledge is None:
            return _err(
                "invalid_params",
                "knowledge base unavailable — pagination patterns not loaded",
                operation_id=operation_id,
            )
        pattern = knowledge.pagination_for(operation_id)
        if pattern is None:
            return _err(
                "invalid_params",
                f"{operation_id} has no pagination pattern — use ozon_call_method",
                operation_id=operation_id,
            )
        return await _fetch_all_pages(
            catalog=catalog,
            knowledge=knowledge,
            seller_client=seller_client,
            performance_client=performance_client,
            operation_id=operation_id,
            base_params=params or {},
            pattern=pattern,
            max_items=max_items,
            cabinet_tier=cabinet_tier,
        )


async def _call_method(
    *,
    catalog: Catalog,
    knowledge: KnowledgeBase | None,
    seller_client: SellerClient | None,
    performance_client: PerformanceClient | None,
    operation_id: str,
    params: dict[str, Any] | None,
    confirm_write: bool,
    i_understand_this_modifies_data: bool,
    cabinet_tier: str | None,
) -> dict[str, Any]:
    method = catalog.get_by_operation_id(operation_id)
    if method is None:
        return _err(
            "not_found",
            f"operation_id {operation_id!r} not found",
            operation_id=operation_id,
            error="NotFound",
        )

    if method.safety == "write" and not confirm_write:
        return _err(
            "write_requires_confirmation",
            (
                f"Method {operation_id} is classified as 'write' (modifies data on "
                f"Ozon server-side) and requires explicit confirmation. Pass "
                f"confirm_write=True to proceed. Reason: {method.safety_reason}"
            ),
            operation_id=operation_id,
            error="WriteRequiresConfirmation",
            payload={"safety": method.safety, "safety_reason": method.safety_reason},
            # Backwards-compat: existing callers read these top-level keys.
            safety=method.safety,
            safety_reason=method.safety_reason,
        )
    if method.safety == "destructive" and not (
        confirm_write and i_understand_this_modifies_data
    ):
        return _err(
            "destructive_requires_double_confirmation",
            (
                f"Method {operation_id} is classified as 'destructive' (deletes / "
                f"cancels / archives data) and requires BOTH confirm_write=True "
                f"AND i_understand_this_modifies_data=True. "
                f"Reason: {method.safety_reason}"
            ),
            operation_id=operation_id,
            error="DestructiveRequiresDoubleConfirmation",
            payload={"safety": method.safety, "safety_reason": method.safety_reason},
            safety=method.safety,
            safety_reason=method.safety_reason,
        )

    gate = _subscription_gate_check(knowledge, method, cabinet_tier)
    if gate is not None:
        return gate

    client: SellerClient | PerformanceClient | None = (
        seller_client if method.api == "seller" else performance_client
    )
    if client is None:
        return _err(
            "missing_credentials",
            (
                f"{method.api} credentials not configured — "
                f"set OZON_CLIENT_ID/OZON_API_KEY (seller) or "
                f"OZON_PERFORMANCE_CLIENT_ID/OZON_PERFORMANCE_CLIENT_SECRET (performance)"
            ),
            operation_id=operation_id,
            error="MissingCredentials",
        )

    body = params or {}
    try:
        _validate(method.request_schema, body)
    except OzonClientValidationError as e:
        return _err(
            "invalid_params",
            e.message,
            operation_id=operation_id,
            error="OzonClientValidationError",
            payload=e.payload,
        )

    async def request_func() -> dict[str, Any]:
        return await client.request(
            method.method,
            method.path,
            json_body=body if method.method != "GET" else None,
            operation_id=operation_id,
            section=method.section,
            with_retry=False,
        )

    return await _execute_with_retry(
        request_func,
        operation_id=operation_id,
        endpoint=method.path,
    )


async def _fetch_all_pages(
    *,
    catalog: Catalog,
    knowledge: KnowledgeBase | None,
    seller_client: SellerClient | None,
    performance_client: PerformanceClient | None,
    operation_id: str,
    base_params: dict[str, Any],
    pattern: PaginationPattern,
    max_items: int,
    cabinet_tier: str | None,
) -> dict[str, Any]:
    all_items: list[Any] = []
    pages_fetched = 0

    page_size = min(pattern.default_limit, pattern.max_limit, max(1, max_items))
    offset = 0
    page_number = 1
    cursor_value: str | None = None
    last_id_value: Any = None
    page_token_value: str | None = None
    # Track previous cursor / last_id / page_token to detect a stuck server
    # that returns the same advancement value forever. Without this we'd
    # loop until max_items is hit.
    prev_cursor_value: str | None = None
    prev_last_id_value: Any = object()
    prev_page_token_value: str | None = None

    while True:
        params: dict[str, Any] = dict(base_params)
        params[pattern.request_limit_field] = page_size

        offset_field = pattern.request_offset_field
        if pattern.type == "offset_limit" and offset_field:
            params[offset_field] = offset
        elif pattern.type == "page_number" and offset_field:
            params[offset_field] = page_number
        elif pattern.type == "last_id" and offset_field:
            if last_id_value is not None:
                params[offset_field] = last_id_value
            else:
                params.setdefault(offset_field, "")
        elif pattern.type == "cursor" and offset_field:
            if cursor_value is not None:
                params[offset_field] = cursor_value
            else:
                params.setdefault(offset_field, "")
        elif pattern.type == "page_token" and offset_field:
            if page_token_value is not None:
                params[offset_field] = page_token_value
            else:
                params.setdefault(offset_field, "")

        result = await _call_method(
            catalog=catalog,
            knowledge=knowledge,
            seller_client=seller_client,
            performance_client=performance_client,
            operation_id=operation_id,
            params=params,
            confirm_write=False,
            i_understand_this_modifies_data=False,
            cabinet_tier=cabinet_tier,
        )

        if not result.get("ok"):
            # Propagate the error envelope but include partial progress
            # so callers can decide whether to keep what we got.
            result.setdefault("partial_items", all_items)
            result.setdefault("pages_fetched", pages_fetched)
            return result

        response = result.get("response") or {}
        items = _extract_items(response, pattern.response_items_field)
        if not isinstance(items, list):
            items = []

        all_items.extend(items)
        pages_fetched += 1

        if len(all_items) >= max_items:
            break
        if not items or len(items) < page_size:
            break

        # Advance the pagination cursor for the next iteration. For
        # cursor/last_id/page_token, also detect the upstream returning
        # the same advancement value twice in a row — that means the API
        # got stuck and another iteration would loop forever.
        if pattern.type == "offset_limit":
            offset += page_size
        elif pattern.type == "page_number":
            page_number += 1
        elif pattern.type == "last_id":
            new_last_id: Any = _extract_field(
                response, pattern.response_total_field
            )
            if new_last_id in (None, "", 0):
                new_last_id = _last_id_from_item(items[-1])
                if new_last_id is None:
                    break
            if new_last_id == prev_last_id_value:
                break  # API returned the same last_id twice — stop.
            prev_last_id_value = new_last_id
            last_id_value = new_last_id
        elif pattern.type == "cursor":
            new_cursor = (
                _extract_field(response, pattern.response_total_field)
                or _extract_field(response, "cursor")
            )
            if not new_cursor:
                break
            if new_cursor == prev_cursor_value:
                break  # API returned the same cursor twice — stop.
            prev_cursor_value = new_cursor
            cursor_value = new_cursor
        elif pattern.type == "page_token":
            new_token = _extract_field(response, "next_page_token") or (
                _extract_field(response, pattern.response_total_field)
            )
            if not new_token:
                break
            if new_token == prev_page_token_value:
                break  # API returned the same page_token twice — stop.
            prev_page_token_value = new_token
            page_token_value = new_token

        # Polite pacing between page requests; rate-limit semaphore handles
        # the slow endpoints separately, so this is just a no-op for fast
        # ones and a cheap insurance against burst patterns.
        await asyncio.sleep(0.05)

    truncated = len(all_items) >= max_items
    return {
        "ok": True,
        "items": all_items[:max_items],
        "total_fetched": min(len(all_items), max_items),
        "truncated": truncated,
        "pages_fetched": pages_fetched,
    }


def _extract_items(response: dict[str, Any], items_field: str) -> Any:
    """Return the array Ozon nested at ``items_field``, walking ``result``."""
    if items_field in response:
        return response[items_field]
    inner = response.get("result")
    if isinstance(inner, dict) and items_field in inner:
        return inner[items_field]
    if isinstance(inner, list) and items_field == "result":
        return inner
    return []


def _extract_field(response: dict[str, Any], field: str | None) -> Any:
    """Look up ``field`` on the response, walking into ``result`` if nested.

    Ozon's list endpoints sometimes return the cursor/last_id at the top
    level (``response[field]``) and sometimes wrap everything inside
    ``response.result.field``. The paginator must look in both places.
    Returns ``None`` when ``field`` is ``None`` or not present.
    """
    if not field:
        return None
    if field in response:
        return response[field]
    inner = response.get("result")
    if isinstance(inner, dict) and field in inner:
        return inner[field]
    return None


def _last_id_from_item(item: Any) -> Any:
    if isinstance(item, dict):
        for key in ("last_id", "id", "product_id", "posting_number", "operation_id"):
            if key in item:
                return item[key]
    return None


def _subscription_gate_check(
    knowledge: KnowledgeBase | None,
    method: Any,
    explicit_cabinet_tier: str | None,
) -> dict[str, Any] | None:
    """Return a subscription_gate refusal dict, or None if the call may proceed."""
    if knowledge is None or not method.operation_id:
        return None
    override = knowledge.subscription_for(method.operation_id)
    if override is None or override.required_tier in (None, "unknown"):
        return None

    cabinet_tier = explicit_cabinet_tier or state.get_cabinet_tier()
    if cabinet_tier is None:
        return None

    if tier_sufficient(cabinet_tier, override.required_tier):
        return None

    return _err(
        "subscription_gate",
        f"Endpoint requires {override.required_tier}, cabinet has {cabinet_tier}",
        code=7,
        operation_id=method.operation_id,
        endpoint=method.path,
        required_tier=override.required_tier,
        cabinet_tier=cabinet_tier,
        retryable=False,
        http_call_skipped=True,
        payload={"source": override.source, "note": override.note},
    )


def _validate(schema: dict[str, Any] | None, payload: dict[str, Any]) -> None:
    if not schema:
        return
    try:
        jsonschema.validate(
            payload,
            schema,
            cls=jsonschema.Draft202012Validator,
        )
    except jsonschema.ValidationError as e:
        raise OzonClientValidationError(
            f"client-side validation failed: {e.message}",
            payload={
                "path": list(e.absolute_path),
                "validator": e.validator,
                "validator_value": e.validator_value,
            },
        ) from e
    except jsonschema.SchemaError:
        return
    except Exception as e:
        module = type(e).__module__ or ""
        if module.startswith(("jsonschema", "referencing")):
            return
        raise
