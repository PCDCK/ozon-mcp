"""Top-level safety net for MCP tool handlers.

The MCP stdio protocol collapses into ``Connection closed`` the moment a
tool handler raises an unhandled exception — the client sees no stack
trace, so the next operator spends hours guessing. The ``@safe_tool``
decorator wraps every handler with:

* a structured log entry on both entry and exit (with duration),
* a ``try``/``except`` that converts **any** escaping exception into the
  canonical ``OzonError`` envelope so the server stays alive and the
  caller gets a typed, parseable response,
* a stderr-logged traceback for diagnostics.

Apply this to every ``@mcp.tool()`` that touches the network or otherwise
does non-trivial work. Read-only pure-Python tools (``ozon_list_sections``
and friends) are low-risk but still benefit from the latency log.
"""

from __future__ import annotations

import functools
import inspect
import time
import traceback
from collections.abc import Callable
from typing import Any, TypeVar

import structlog

from ozon_mcp.schema.errors import OzonError as OzonErrorModel

log = structlog.get_logger()

F = TypeVar("F", bound=Callable[..., Any])


def _envelope(exc: BaseException, operation_id: str | None) -> dict[str, Any]:
    """Build the canonical error envelope for an unexpected exception.

    Kept deliberately defensive: even if ``OzonErrorModel`` itself raises
    (e.g. pydantic rejects one of our fields), we return a hand-built dict
    so the tool response is never *also* an exception.
    """
    try:
        return OzonErrorModel(
            error="internal",
            error_type="internal",
            message=f"{type(exc).__name__}: {exc}",
            operation_id=operation_id,
            payload={"exception_class": type(exc).__name__},
        ).to_dict()
    except Exception:
        return {
            "error": "internal",
            "error_type": "internal",
            "message": f"{type(exc).__name__}: {exc}",
            "operation_id": operation_id,
            "exception_class": type(exc).__name__,
        }


def safe_tool(func: F) -> F:  # noqa: UP047 — stay on pre-PEP-695 TypeVar for py3.12
    """Wrap an MCP tool handler so unhandled exceptions become envelopes.

    Works on both sync and async handlers. Logs entry/exit events with a
    ``duration_ms`` field so operators can see slow tools in the stream.
    """
    tool_name = func.__name__
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            operation_id = kwargs.get("operation_id")
            start = time.monotonic()
            log.debug("tool_entry", tool=tool_name, operation_id=operation_id)
            try:
                result = await func(*args, **kwargs)
            except BaseException as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                tb = traceback.format_exc()
                log.error(
                    "tool_crashed",
                    tool=tool_name,
                    operation_id=operation_id,
                    exception_class=type(exc).__name__,
                    exception=str(exc),
                    duration_ms=duration_ms,
                    traceback=tb,
                )
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    # Shutdown signals still need to propagate.
                    raise
                return _envelope(exc, operation_id)
            duration_ms = int((time.monotonic() - start) * 1000)
            log.debug(
                "tool_exit",
                tool=tool_name,
                operation_id=operation_id,
                duration_ms=duration_ms,
            )
            return result

        return _async_wrapper  # type: ignore[return-value]

    @functools.wraps(func)
    def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        operation_id = kwargs.get("operation_id")
        start = time.monotonic()
        log.debug("tool_entry", tool=tool_name, operation_id=operation_id)
        try:
            result = func(*args, **kwargs)
        except BaseException as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            tb = traceback.format_exc()
            log.error(
                "tool_crashed",
                tool=tool_name,
                operation_id=operation_id,
                exception_class=type(exc).__name__,
                exception=str(exc),
                duration_ms=duration_ms,
                traceback=tb,
            )
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return _envelope(exc, operation_id)
        duration_ms = int((time.monotonic() - start) * 1000)
        log.debug(
            "tool_exit",
            tool=tool_name,
            operation_id=operation_id,
            duration_ms=duration_ms,
        )
        return result

    return _sync_wrapper  # type: ignore[return-value]
