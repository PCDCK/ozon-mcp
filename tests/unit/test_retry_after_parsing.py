"""RFC 7231 ``Retry-After`` header parsing.

Per the spec the value is either delta-seconds (``"60"``) or an
HTTP-date (``"Wed, 21 Oct 2026 07:28:00 GMT"``). We accept both,
clamp negatives, and return None for garbage.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ozon_mcp.transport.base import _parse_retry_after


def test_delta_seconds_integer() -> None:
    assert _parse_retry_after("60") == 60.0


def test_delta_seconds_float() -> None:
    assert _parse_retry_after("0.5") == 0.5


def test_delta_seconds_zero() -> None:
    assert _parse_retry_after("0") == 0.0


def test_delta_seconds_negative_clamped() -> None:
    assert _parse_retry_after("-5") == 0.0


def test_http_date_in_future() -> None:
    when = datetime.now(UTC) + timedelta(seconds=120)
    header = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
    parsed = _parse_retry_after(header)
    assert parsed is not None
    # Allow ±5s tolerance for the round trip through the formatter.
    assert 110 <= parsed <= 130


def test_http_date_in_past_clamped_to_zero() -> None:
    when = datetime.now(UTC) - timedelta(hours=1)
    header = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert _parse_retry_after(header) == 0.0


def test_garbage_returns_none() -> None:
    assert _parse_retry_after("not-a-date-at-all") is None


def test_empty_header_returns_none() -> None:
    assert _parse_retry_after("") is None
    assert _parse_retry_after(None) is None
