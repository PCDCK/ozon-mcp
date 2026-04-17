"""Process-local shared state for the MCP server.

Kept tiny on purpose — only values that genuinely need to be shared
across tool modules live here. Right now that is the last-seen cabinet
subscription tier, so the execution pre-check can see what
``ozon_get_subscription_status`` cached without threading an extra
parameter through every tool call.

The cache has a TTL (``_TTL_SECONDS``) — Ozon subscriptions change
rarely but they DO change (upgrades / downgrades / lapses). Without an
expiry an upgrade taken hours ago would never be reflected in the
gate decision until the process restarts.
"""

from __future__ import annotations

import time

# Subscriptions change rarely but not never — refresh once per hour at
# the latest. Callers can force a refresh sooner via
# ``ozon_get_subscription_status(refresh=True)``.
_TTL_SECONDS: float = 3600.0

_cabinet_tier: str | None = None
_cabinet_tier_set_at: float | None = None


def set_cabinet_tier(tier: str | None) -> None:
    """Record the current cabinet's subscription tier (e.g. ``PREMIUM_PLUS``).

    Called by ``ozon_get_subscription_status`` after it reads
    /v1/seller/info. Silently accepts unknown / falsy values by clearing
    the cache.

    Errors must NOT call this — only success paths should record a tier.
    """
    global _cabinet_tier, _cabinet_tier_set_at
    if tier and isinstance(tier, str):
        _cabinet_tier = tier.upper()
        _cabinet_tier_set_at = time.monotonic()
    else:
        _cabinet_tier = None
        _cabinet_tier_set_at = None


def get_cabinet_tier() -> str | None:
    """Return the cached cabinet tier if it is still fresh, else None."""
    if _cabinet_tier is None or _cabinet_tier_set_at is None:
        return None
    if time.monotonic() - _cabinet_tier_set_at > _TTL_SECONDS:
        return None
    return _cabinet_tier


def cabinet_tier_age_seconds() -> float | None:
    """Return how many seconds ago the tier was cached, or None."""
    if _cabinet_tier_set_at is None:
        return None
    return time.monotonic() - _cabinet_tier_set_at


def reset() -> None:
    """Test helper — forget the cached tier."""
    global _cabinet_tier, _cabinet_tier_set_at
    _cabinet_tier = None
    _cabinet_tier_set_at = None
