"""Subscription tier tools.

Two complementary tools:

- ``ozon_list_methods_for_subscription`` works offline using auto-extracted
  subscription mentions from each method's documentation. Lets an agent
  answer "what methods need Premium Plus?" without any API call.

- ``ozon_get_subscription_status`` actually calls /v1/seller/info to read
  the current account's subscription tier. Available only when seller
  credentials are configured. Result is cached per process for an hour
  (matches state.py TTL); pass ``refresh=True`` to bypass the cache.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ozon_mcp import state
from ozon_mcp.errors import OzonError
from ozon_mcp.schema import Catalog
from ozon_mcp.schema.errors import OzonError as OzonErrorModel
from ozon_mcp.schema.extractor import SUBSCRIPTION_TIERS
from ozon_mcp.tools._safety import safe_tool
from ozon_mcp.transport.seller import SellerClient

_SELLER_INFO_PATH = "/v1/seller/info"
_SELLER_INFO_OP = "SellerAPI_SellerInfo"


def _err(error_type: str, message: str, **fields: Any) -> dict[str, Any]:
    """Build the canonical error envelope (matches execution.py shape)."""
    return OzonErrorModel(
        error=fields.pop("error", error_type),
        error_type=error_type,  # type: ignore[arg-type]
        message=message,
        **fields,
    ).to_dict()


def register(
    mcp: FastMCP,
    catalog: Catalog,
    seller_client: SellerClient | None,
) -> None:
    @mcp.tool()
    @safe_tool
    def ozon_list_methods_for_subscription(tier: str) -> dict[str, Any]:
        """List all Ozon methods that mention a specific subscription tier.

        Useful when an agent wants to know "what extra capabilities do I
        unlock by upgrading to Premium Plus?" or "which methods will fail
        without Premium?". Tiers are auto-extracted from method
        documentation, so this is a hint, not a contract — the actual
        hard 403 set may differ.

        Args:
            tier: one of UNSPECIFIED, PREMIUM_LITE, PREMIUM, PREMIUM_PLUS,
                PREMIUM_PRO
        """
        normalized = tier.upper().replace(" ", "_").replace("-", "_")
        if normalized not in SUBSCRIPTION_TIERS:
            return _err(
                "invalid_params",
                f"unknown tier {tier!r}",
                payload={"valid_tiers": list(SUBSCRIPTION_TIERS)},
                # Backwards-compat: legacy callers read these top-level keys.
                valid_tiers=list(SUBSCRIPTION_TIERS),
            )
        matches = [
            m for m in catalog.methods
            if normalized in m.subscription_tiers_mentioned
        ]
        return {
            "tier": normalized,
            "count": len(matches),
            "methods": [
                {
                    "operation_id": m.operation_id,
                    "api": m.api,
                    "method": m.method,
                    "path": m.path,
                    "section": m.section,
                    "summary": m.summary,
                    "all_tiers_mentioned": m.subscription_tiers_mentioned,
                    "min_tier_hint": m.subscription_min_tier,
                }
                for m in matches
            ],
        }

    if seller_client is None:
        return

    cache: dict[str, Any] = {}

    @mcp.tool()
    @safe_tool
    async def ozon_get_subscription_status(refresh: bool = False) -> dict[str, Any]:
        """Get the current account's subscription tier from /v1/seller/info.

        Returns the subscription type, the is_premium flag, plus the list
        of all Ozon API methods that *might* require this exact tier.
        Result is cached per server process; pass ``refresh=True`` to
        bypass the cache. Errors are NEVER cached.

        Available only when seller credentials are configured.
        """
        if cache and not refresh:
            return dict(cache)

        try:
            response = await seller_client.request(
                "POST",
                _SELLER_INFO_PATH,
                json_body={},
                operation_id=_SELLER_INFO_OP,
            )
        except OzonError as e:
            # Translate the typed exception into the canonical envelope so
            # callers can branch on error_type alongside execution.py
            # responses. The error is NOT cached — next call retries.
            return _err(
                _classify_error(e),
                e.message,
                code=e.status_code,
                status_code=e.status_code,
                operation_id=_SELLER_INFO_OP,
                endpoint=_SELLER_INFO_PATH,
                retryable=_is_retryable(e),
                payload=e.payload,
            )

        sub = (response.get("subscription") or {}) if isinstance(response, dict) else {}
        tier = sub.get("type") if isinstance(sub, dict) else None
        is_premium = sub.get("is_premium") if isinstance(sub, dict) else None

        result: dict[str, Any] = {
            "subscription_type": tier,
            "is_premium": is_premium,
            "raw_subscription": sub,
        }
        if isinstance(tier, str) and tier in SUBSCRIPTION_TIERS:
            same_tier_methods = [
                m for m in catalog.methods if tier in m.subscription_tiers_mentioned
            ]
            result["methods_mentioning_this_tier"] = [
                {
                    "operation_id": m.operation_id,
                    "summary": m.summary,
                    "section": m.section,
                }
                for m in same_tier_methods
            ]

        cache.clear()
        cache.update(result)
        # Make the current tier visible to the execution layer so the
        # subscription gate can pre-reject calls that would 403.
        state.set_cabinet_tier(tier if isinstance(tier, str) else None)
        return result


def _classify_error(e: OzonError) -> str:
    """Map OzonError exception subclass to envelope error_type."""
    name = type(e).__name__
    return {
        "OzonRateLimitError": "rate_limit",
        "OzonServerError": "server_error",
        "OzonAuthError": "auth",
        "OzonForbiddenError": "forbidden",
        "OzonNotFoundError": "not_found",
        "OzonConflictError": "conflict",
        "OzonValidationError": "invalid_params",
    }.get(name, "unknown")


def _is_retryable(e: OzonError) -> bool:
    name = type(e).__name__
    return name in {"OzonRateLimitError", "OzonServerError"}
