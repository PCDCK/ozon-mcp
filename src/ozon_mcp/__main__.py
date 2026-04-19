"""ozon-mcp CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys

from ozon_mcp import __version__
from ozon_mcp.server import create_server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ozon-mcp",
        description=(
            "MCP server for the Ozon Seller and Performance APIs. "
            "Speaks the MCP stdio protocol — point any MCP-compatible "
            "client at this command to expose 15 tools and 13 curated "
            "workflows. With no flags, reads OZON_* credentials from "
            "the environment and starts the server on stdio."
        ),
        epilog=(
            "Configure your client (Claude Desktop, Claude Code, "
            "Cursor, Cline, Continue, ...) to launch this command — "
            "see README.md for per-client snippets."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ozon-mcp {__version__}",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help=(
            "Run a connectivity probe against /v1/seller/info instead of "
            "starting the stdio server. Prints the subscription tier and "
            "exits 0 on success, non-zero with a traceback on failure. "
            "Useful when the MCP client reports 'Connection closed' and "
            "you need to see the real error."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point.

    Parses ``--version`` / ``--help`` / ``--diagnose`` then drops into
    the FastMCP stdio loop. ``--diagnose`` bypasses MCP stdio entirely
    so any crash in the transport layer is visible as a stack trace
    rather than a silent pipe close.
    """
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.diagnose:
        sys.exit(_run_diagnose())
    server = create_server()
    server.run(transport="stdio")


def _run_diagnose() -> int:
    """Out-of-band connectivity probe. Mirrors scripts/diagnose_live_call.py.

    Kept in the CLI so users can invoke it without checking out the repo:
    ``uv run ozon-mcp --diagnose`` is the supported debug entry point.
    """
    from ozon_mcp.config import Config
    from ozon_mcp.knowledge import load_knowledge
    from ozon_mcp.server import _configure_logging
    from ozon_mcp.transport.ratelimit import RateLimitRegistry
    from ozon_mcp.transport.seller import SellerClient

    config = Config()
    _configure_logging(config.log_level)
    if not config.has_seller_credentials():
        print("ERROR: OZON_CLIENT_ID / OZON_API_KEY not set.", file=sys.stderr)
        return 2

    async def _probe() -> int:
        knowledge = load_knowledge()
        rate_limits = RateLimitRegistry(knowledge)
        client = SellerClient(
            config.seller_client_id(),
            config.seller_api_key(),
            rate_limits=rate_limits,
        )
        try:
            resp = await client.request(
                "POST",
                "/v1/seller/info",
                json_body={},
                operation_id="SellerAPI_SellerInfo",
            )
        except BaseException as exc:
            import traceback
            print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc()
            return 1
        finally:
            await client.aclose()
        sub = resp.get("subscription") if isinstance(resp, dict) else None
        print(f"OK subscription={sub}", file=sys.stderr)
        return 0

    return asyncio.run(_probe())


if __name__ == "__main__":
    main()
