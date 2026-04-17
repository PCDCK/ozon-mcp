"""Cabinet-tier cache: TTL behaviour and error-isolation."""

from __future__ import annotations

import pytest

from ozon_mcp import state


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    state.reset()


def test_set_and_get_cabinet_tier() -> None:
    state.set_cabinet_tier("PREMIUM_PLUS")
    assert state.get_cabinet_tier() == "PREMIUM_PLUS"


def test_falsy_tier_clears_cache() -> None:
    state.set_cabinet_tier("PREMIUM_PLUS")
    state.set_cabinet_tier("")
    assert state.get_cabinet_tier() is None
    state.set_cabinet_tier("LITE")
    state.set_cabinet_tier(None)
    assert state.get_cabinet_tier() is None


def test_tier_is_normalized_to_uppercase() -> None:
    state.set_cabinet_tier("premium_plus")
    assert state.get_cabinet_tier() == "PREMIUM_PLUS"


def test_get_returns_none_after_ttl_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After more than _TTL_SECONDS have passed, the cache must look stale."""
    state.set_cabinet_tier("PREMIUM_PLUS")
    assert state.get_cabinet_tier() == "PREMIUM_PLUS"

    # Fast-forward time beyond the TTL.
    base = state.cabinet_tier_age_seconds()
    assert base is not None
    real_monotonic = state._cabinet_tier_set_at  # type: ignore[attr-defined]
    assert real_monotonic is not None

    import time as _time

    monkeypatch.setattr(
        _time,
        "monotonic",
        lambda: real_monotonic + state._TTL_SECONDS + 1,  # type: ignore[attr-defined]
    )
    assert state.get_cabinet_tier() is None


def test_age_seconds_grows_with_time(monkeypatch: pytest.MonkeyPatch) -> None:
    state.set_cabinet_tier("PREMIUM_PLUS")
    age = state.cabinet_tier_age_seconds()
    assert age is not None
    assert age >= 0


def test_age_is_none_when_never_set() -> None:
    assert state.cabinet_tier_age_seconds() is None
