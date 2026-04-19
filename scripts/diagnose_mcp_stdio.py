"""Drive the ozon-mcp stdio server end-to-end — initialize, call a tool,
capture stderr so we can see the traceback when the server dies.

This mirrors exactly what Claude Code does: spawn ``ozon-mcp``, speak
JSON-RPC over stdin/stdout, pipe stderr separately. Unlike the MCP
client libraries, we DO NOT hide server stderr — we print it all
on exit so any unhandled exception is visible.

Usage::

    OZON_CLIENT_ID=... OZON_API_KEY=... \\
        uv run python scripts/diagnose_mcp_stdio.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


async def _read_message(stream: asyncio.StreamReader) -> dict | None:
    """Read one newline-delimited JSON-RPC message from the server."""
    line = await stream.readline()
    if not line:
        return None
    try:
        return json.loads(line.decode("utf-8"))
    except json.JSONDecodeError:
        print(f"<<< non-json from server: {line!r}", file=sys.stderr)
        return None


def _send(stream: asyncio.StreamWriter, payload: dict) -> None:
    blob = (json.dumps(payload) + "\n").encode("utf-8")
    stream.write(blob)


@asynccontextmanager
async def _spawn() -> AsyncIterator[asyncio.subprocess.Process]:
    env = os.environ.copy()
    env.setdefault("OZON_LOG_LEVEL", "DEBUG")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # Run via uv from the repo root.
    proc = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "ozon-mcp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        yield proc
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                proc.kill()
                await proc.wait()


async def _pump_stderr(proc: asyncio.subprocess.Process) -> None:
    assert proc.stderr is not None
    while True:
        line = await proc.stderr.readline()
        if not line:
            return
        sys.stderr.write("[server] " + line.decode("utf-8", errors="replace"))
        sys.stderr.flush()


async def _main() -> int:
    async with _spawn() as proc:
        assert proc.stdin is not None and proc.stdout is not None
        stderr_task = asyncio.create_task(_pump_stderr(proc))

        # 1. initialize
        _send(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "diagnose", "version": "0"},
                },
            },
        )
        await proc.stdin.drain()
        init_resp = await asyncio.wait_for(_read_message(proc.stdout), timeout=30)
        print("INIT:", init_resp, file=sys.stderr)

        _send(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        await proc.stdin.drain()

        # 2. call tool: ozon_get_subscription_status (no args)
        _send(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "ozon_get_subscription_status",
                    "arguments": {},
                },
            },
        )
        await proc.stdin.drain()
        try:
            call_resp = await asyncio.wait_for(_read_message(proc.stdout), timeout=60)
            print("CALL1:", call_resp, file=sys.stderr)
        except TimeoutError:
            print("TIMEOUT waiting for tool response", file=sys.stderr)

        # 3. call tool: ozon_call_method ProductAPI_GetProductList (10 items)
        _send(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ozon_call_method",
                    "arguments": {
                        "operation_id": "ProductAPI_GetProductList",
                        "params": {"filter": {"visibility": "ALL"}, "limit": 10},
                    },
                },
            },
        )
        await proc.stdin.drain()
        try:
            call2_resp = await asyncio.wait_for(_read_message(proc.stdout), timeout=60)
            print("CALL2:", call2_resp, file=sys.stderr)
        except TimeoutError:
            print("TIMEOUT waiting for tool response (call 2)", file=sys.stderr)

        # Give the server a moment to flush stderr if it died.
        await asyncio.sleep(0.3)
        rc = proc.returncode
        print(f"server returncode={rc}", file=sys.stderr)
        stderr_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stderr_task
        return rc or 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_main()))
    except KeyboardInterrupt:
        sys.exit(130)
