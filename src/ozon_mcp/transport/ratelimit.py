"""Per-section rate limiter built on top of aiolimiter.

Resolution order for any (api, operation_id, section) tuple:
    1. Per-method override from knowledge/rate_limits.yaml
    2. Per-(api, section) override
    3. Per-api global default (from yaml entry with section=null)
    4. Hard-coded fallback (1000/min) if knowledge base is unavailable
"""

from __future__ import annotations

from aiolimiter import AsyncLimiter

from ozon_mcp.knowledge import KnowledgeBase

_HARDCODED_DEFAULT_PER_MINUTE = 1000


class RateLimitRegistry:
    """Holds one AsyncLimiter per scope and reuses them across calls."""

    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self._kb = kb
        self._limiters: dict[tuple[str, str], AsyncLimiter] = {}
        self._global: dict[str, AsyncLimiter] = {}
        for api_label in ("seller", "performance"):
            per_minute = _resolve_global(kb, api_label)
            self._global[api_label] = AsyncLimiter(per_minute, time_period=60)

    def for_call(
        self,
        api: str,
        operation_id: str | None,
        section: str | None,
    ) -> AsyncLimiter:
        if self._kb is not None and operation_id:
            rl = self._kb.rate_limit_for(operation_id, api=api, section=section)
            if rl is not None and rl.per_minute is not None:
                if rl.operation_id:
                    key = (api, f"op:{rl.operation_id}")
                else:
                    key = (api, f"sec:{rl.section}")
                if key not in self._limiters:
                    self._limiters[key] = AsyncLimiter(rl.per_minute, time_period=60)
                return self._limiters[key]
        return self._global.get(api) or self._global["seller"]


def _resolve_global(kb: KnowledgeBase | None, api_label: str) -> int:
    if kb is None:
        return _HARDCODED_DEFAULT_PER_MINUTE
    for rl in kb.rate_limits:
        if rl.api == api_label and rl.section is None and rl.per_minute is not None:
            return rl.per_minute
    return _HARDCODED_DEFAULT_PER_MINUTE
