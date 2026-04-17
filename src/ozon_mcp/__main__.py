"""ozon-mcp CLI entry point."""

from __future__ import annotations

import argparse
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
    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point.

    Parses ``--version`` / ``--help`` then drops into the FastMCP stdio
    loop. Anything beyond those two flags is rejected with a clean
    usage message — so ``uv run ozon-mcp --help`` is a safe smoke test
    that does NOT launch the server.
    """
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    # ``args`` carries no positional/flag info we use — argparse already
    # handled --version/--help and exited. Accessing it keeps mypy happy.
    _ = args
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
