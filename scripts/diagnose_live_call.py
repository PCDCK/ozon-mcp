"""Out-of-band diagnostic: make a real /v1/seller/info call and print the
full traceback of any crash.

Why this exists: the MCP stdio protocol silently closes the pipe when the
server process dies, so clients see only ``Connection closed`` with no
stack trace. Running the transport layer directly from Python surfaces
the real exception.

Usage (from the ozon-mcp repo root)::

    OZON_CLIENT_ID=... OZON_API_KEY=... OZON_LOG_LEVEL=DEBUG \\
        uv run python scripts/diagnose_live_call.py

On success prints the subscription tier and exits 0. On any failure
prints the full traceback to stderr and exits non-zero.
"""

from __future__ import annotations

import asyncio
import sys
import traceback

from ozon_mcp.config import Config
from ozon_mcp.knowledge import load_knowledge
from ozon_mcp.server import _configure_logging
from ozon_mcp.transport.ratelimit import RateLimitRegistry
from ozon_mcp.transport.seller import SellerClient


async def _probe() -> int:
    config = Config()
    if not config.has_seller_credentials():
        print("ERROR: OZON_CLIENT_ID / OZON_API_KEY not set in env.", file=sys.stderr)
        return 2

    _configure_logging(config.log_level)
    knowledge = load_knowledge()
    rate_limits = RateLimitRegistry(knowledge)

    client = SellerClient(
        config.seller_client_id(),
        config.seller_api_key(),
        rate_limits=rate_limits,
    )
    try:
        response = await client.request(
            "POST",
            "/v1/seller/info",
            json_body={},
            operation_id="SellerAPI_SellerInfo",
        )
    except BaseException:
        print("---- diagnose: request raised ----", file=sys.stderr)
        traceback.print_exc()
        return 1
    finally:
        await client.aclose()

    sub = response.get("subscription") if isinstance(response, dict) else None
    print("OK", file=sys.stderr)
    print(f"subscription={sub}", file=sys.stderr)
    return 0


def main() -> None:
    try:
        rc = asyncio.run(_probe())
    except BaseException:
        print("---- diagnose: top-level raised ----", file=sys.stderr)
        traceback.print_exc()
        sys.exit(3)
    sys.exit(rc)


if __name__ == "__main__":
    main()
