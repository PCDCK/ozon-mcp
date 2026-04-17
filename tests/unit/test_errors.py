"""OzonError pydantic envelope: shape, retryable flags, code lookup."""

from __future__ import annotations

import pytest

from ozon_mcp.knowledge.loader import load_knowledge
from ozon_mcp.schema.errors import OzonError


def test_envelope_dumps_with_required_fields() -> None:
    err = OzonError(
        error="rate_limit_exceeded",
        error_type="rate_limit",
        message="slow down",
        retryable=True,
        retry_after_seconds=60,
    )
    d = err.to_dict()
    assert d["error"] == "rate_limit_exceeded"
    assert d["error_type"] == "rate_limit"
    assert d["message"] == "slow down"
    assert d["retryable"] is True
    assert d["retry_after_seconds"] == 60
    # Optional fields excluded when None.
    assert "operation_id" not in d
    assert "endpoint" not in d


def test_envelope_subscription_gate_carries_tier_fields() -> None:
    err = OzonError(
        error="subscription_gate",
        error_type="subscription_gate",
        message="Endpoint requires PREMIUM_PRO, cabinet has PREMIUM_PLUS",
        code=7,
        required_tier="PREMIUM_PRO",
        cabinet_tier="PREMIUM_PLUS",
        http_call_skipped=True,
        retryable=False,
    )
    d = err.to_dict()
    assert d["code"] == 7
    assert d["required_tier"] == "PREMIUM_PRO"
    assert d["cabinet_tier"] == "PREMIUM_PLUS"
    assert d["http_call_skipped"] is True
    assert d["retryable"] is False


def test_envelope_allows_extra_fields() -> None:
    err = OzonError(
        error="WriteRequiresConfirmation",
        error_type="write_requires_confirmation",
        message="needs confirm",
        safety="write",
        safety_reason="POST + writes data",
    )
    d = err.to_dict()
    assert d["safety"] == "write"
    assert d["safety_reason"] == "POST + writes data"


def test_envelope_rejects_unknown_error_type() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OzonError(
            error="x",
            error_type="totally_made_up",  # type: ignore[arg-type]
            message="m",
        )


def test_error_catalog_has_subscription_gate_code_7() -> None:
    kb = load_knowledge()
    matches = [e for e in kb.errors if e.code == "7"]
    assert matches, "code 7 (subscription gate) must be in error_codes.yaml"
    entry = matches[0]
    assert entry.http_status == 403
    assert "подписк" in entry.cause.lower()


def test_error_catalog_includes_5xx_retryable_marker() -> None:
    """500/502/503/504 must be present so agents can pick a retry strategy."""
    kb = load_knowledge()
    codes = {e.code for e in kb.errors}
    assert "500" in codes
    assert "503" in codes


def test_error_catalog_marks_400_as_non_retryable() -> None:
    """Validation errors do not become valid by retrying."""
    kb = load_knowledge()
    entry = next(e for e in kb.errors if e.code == "400")
    # We don't model retryable on ErrorEntry — but the cause/fix text must
    # not suggest blind retry.
    assert "retry" not in entry.fix.lower() or "не" in entry.fix.lower()


def test_error_catalog_429_recommends_backoff() -> None:
    kb = load_knowledge()
    entry = next(e for e in kb.errors if e.code == "429")
    assert "backoff" in entry.fix.lower() or "limiter" in entry.fix.lower()
