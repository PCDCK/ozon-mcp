"""Regression tests for ``@safe_tool`` and transport catch-all.

These exist because a single unhandled exception in a tool handler used
to kill the MCP stdio process, and the user saw only ``Connection closed``
with no stack trace. The fix is two-layered: ``@safe_tool`` on every
handler and a catch-all ``except Exception`` in ``BaseClient.request``.
The tests here codify both so a future refactor cannot silently regress
to the old behaviour.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ozon_mcp.errors import OzonError
from ozon_mcp.tools._safety import safe_tool
from ozon_mcp.transport.ratelimit import RateLimitRegistry
from ozon_mcp.transport.seller import SellerClient


@pytest.fixture
def rate_limits() -> RateLimitRegistry:
    return RateLimitRegistry(kb=None)


async def test_safe_tool_converts_async_exception_to_envelope() -> None:
    @safe_tool
    async def failing_tool() -> dict[str, Any]:
        raise RuntimeError("boom")

    result = await failing_tool()  # type: ignore[misc]
    assert result["error_type"] == "internal"
    assert "boom" in result["message"]
    assert result["payload"]["exception_class"] == "RuntimeError"


def test_safe_tool_converts_sync_exception_to_envelope() -> None:
    @safe_tool
    def failing_tool() -> dict[str, Any]:
        raise ValueError("oops")

    result = failing_tool()
    assert result["error_type"] == "internal"
    assert result["payload"]["exception_class"] == "ValueError"


async def test_safe_tool_passes_through_success() -> None:
    @safe_tool
    async def ok_tool() -> dict[str, Any]:
        return {"ok": True}

    assert await ok_tool() == {"ok": True}  # type: ignore[misc]


async def test_safe_tool_reraises_keyboard_interrupt() -> None:
    """Shutdown signals must NOT be swallowed into an envelope."""

    @safe_tool
    async def interrupt_tool() -> dict[str, Any]:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        await interrupt_tool()  # type: ignore[misc]


async def test_transport_wraps_ssl_error_as_ozon_error(
    monkeypatch: pytest.MonkeyPatch, rate_limits: RateLimitRegistry
) -> None:
    """``httpx.HTTPError`` subclasses (SSLError here) must not escape raw."""
    client = SellerClient("c", "k", rate_limits=rate_limits)

    async def fake_request(*args: Any, **kwargs: Any) -> Any:
        raise httpx.ConnectError("TLS handshake failed")

    monkeypatch.setattr(client._client, "request", fake_request)
    with pytest.raises(OzonError) as exc:
        await client.request("POST", "/v1/test", json_body={}, with_retry=False)
    # ConnectError routes through the OzonServerError branch but ultimately
    # is still an OzonError — that's what callers catch on.
    assert "connection" in str(exc.value).lower() or "tls" in str(exc.value).lower()
    await client.aclose()


async def test_transport_wraps_generic_exception_as_ozon_error(
    monkeypatch: pytest.MonkeyPatch, rate_limits: RateLimitRegistry
) -> None:
    """The catch-all ``except Exception`` prevents arbitrary errors from
    killing the MCP process. Without it, a mid-request cancel or a
    third-party middleware bug would surface as a raw exception and
    (via FastMCP stdio) break the pipe.
    """
    client = SellerClient("c", "k", rate_limits=rate_limits)

    async def fake_request(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("something weird")

    monkeypatch.setattr(client._client, "request", fake_request)
    with pytest.raises(OzonError) as exc:
        await client.request("POST", "/v1/test", json_body={}, with_retry=False)
    assert "unexpected transport error" in str(exc.value)
    assert "RuntimeError" in str(exc.value)
    await client.aclose()


async def test_transport_wraps_auth_headers_failure_as_ozon_error(
    monkeypatch: pytest.MonkeyPatch, rate_limits: RateLimitRegistry
) -> None:
    """_auth_headers() used to run OUTSIDE the guarded scope. If OAuth
    refresh (Performance client) or the Seller header builder raised,
    that exception escaped the envelope and killed the process.
    """
    client = SellerClient("c", "k", rate_limits=rate_limits)

    async def exploding_headers() -> dict[str, str]:
        raise RuntimeError("oauth refresh blew up")

    monkeypatch.setattr(client, "_auth_headers", exploding_headers)
    with pytest.raises(OzonError) as exc:
        await client.request("POST", "/v1/test", json_body={}, with_retry=False)
    assert "request setup failed" in str(exc.value)
    await client.aclose()


def test_configure_logging_does_not_write_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression for the v0.6.0 bug: structlog defaulted to stdout, which
    corrupted the MCP JSON-RPC stream. This test asserts structlog's
    logger factory is pointed at stderr by ``_configure_logging``.
    """
    import structlog

    from ozon_mcp.server import _configure_logging

    # ``_configure_logging`` captures ``sys.stderr`` at call time. Once this
    # test exits, pytest's capsys restores the real stderr but structlog
    # still holds a reference to the captured one — that would break every
    # subsequent test that logs. Reset structlog defaults in ``finally``.
    try:
        _configure_logging("INFO")
        structlog.get_logger().info("probe_event", flavour="cinnamon")
        captured = capsys.readouterr()
        assert "probe_event" not in captured.out, (
            "structlog must NOT write to stdout — MCP stdio protocol owns it."
        )
        assert "probe_event" in captured.err
    finally:
        structlog.reset_defaults()
