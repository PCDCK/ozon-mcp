"""Reference tools — rate limits, error catalog, code examples, swagger meta."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from mcp.server.fastmcp import FastMCP

from ozon_mcp.knowledge import KnowledgeBase
from ozon_mcp.schema import Catalog
from ozon_mcp.schema.errors import make_error


def _load_swagger_meta() -> dict[str, Any] | None:
    """Read the bundled swagger_meta.json, tolerating absence.

    The file is produced by parser/parse_swagger.py after each refresh and
    copied into the MCP `data/` directory. Absence means the package was
    built from a pre-v0.6 snapshot — consumers should then treat versions
    as unknown rather than failing.
    """
    try:
        text = (files("ozon_mcp.data") / "swagger_meta.json").read_text(
            encoding="utf-8"
        )
    except (FileNotFoundError, OSError):
        return None
    try:
        parsed: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed


def register(mcp: FastMCP, catalog: Catalog, kb: KnowledgeBase) -> None:
    @mcp.tool()
    def ozon_get_rate_limits(
        operation_id: str | None = None,
        section: str | None = None,
    ) -> dict[str, Any]:
        """Look up rate limits for a method, section, or the whole API.

        Without arguments returns all known limits. With operation_id, returns
        the most specific limit (per-method overrides per-section overrides global).

        NOTE: Many limits in v0.2 are conservative guesses (source: 'guess').
        Verify against real Ozon responses before relying on them in production.
        """
        if operation_id:
            m = catalog.get_by_operation_id(operation_id)
            if m is None:
                return make_error(
                    "not_found",
                    f"operation_id {operation_id!r} not found",
                    operation_id=operation_id,
                    error="NotFound",
                )
            limit = kb.rate_limit_for(operation_id, api=m.api, section=m.section)
            return {
                "operation_id": operation_id,
                "rate_limit": limit.model_dump() if limit else None,
            }
        if section:
            matching = [r for r in kb.rate_limits if r.section == section]
            return {
                "section": section,
                "limits": [r.model_dump() for r in matching],
            }
        return {
            "all_limits": [r.model_dump() for r in kb.rate_limits],
            "disclaimer": "Most limits are 'guess' source; verify before production use.",
        }

    @mcp.tool()
    def ozon_get_error_catalog(
        code: str | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Look up Ozon API errors and their solutions.

        Without arguments returns all known errors. With code (e.g. "429" or
        "InvalidArgument") filters by code. With operation_id returns errors
        specific to that method plus all generic ones.
        """
        if code:
            matches = kb.errors_by_code(code)
            return {
                "code": code,
                "count": len(matches),
                "errors": [e.model_dump() for e in matches],
            }
        if operation_id:
            specific = kb.errors_for(operation_id)
            generic = [e for e in kb.errors if e.operation_id is None]
            return {
                "operation_id": operation_id,
                "specific": [e.model_dump() for e in specific],
                "generic": [e.model_dump() for e in generic],
            }
        return {
            "count": len(kb.errors),
            "errors": [e.model_dump() for e in kb.errors],
        }

    @mcp.tool()
    def ozon_get_examples(operation_id: str) -> dict[str, Any]:
        """Get hand-crafted request examples for one method.

        Examples are real, validated payloads matching the method's request
        schema — copy them as starting points for your own calls.
        """
        if catalog.get_by_operation_id(operation_id) is None:
            return make_error(
                "not_found",
                f"operation_id {operation_id!r} not found",
                operation_id=operation_id,
                error="NotFound",
            )
        examples = kb.examples_for(operation_id)
        return {
            "operation_id": operation_id,
            "count": len(examples),
            "examples": [e.model_dump() for e in examples],
        }

    @mcp.tool()
    def ozon_get_swagger_meta() -> dict[str, Any]:
        """Return metadata about the bundled Ozon swagger snapshots.

        Tells the caller which spec version we are shipping, how many
        methods it contains, when the snapshot was refreshed, and the
        SHA-256 of the file. Useful for:

          - agents that need to decide whether to re-check docs online;
          - operators validating that a refresh actually landed;
          - bug reports — include this in the issue so reproduction is
            exact.

        Returns ``{"error": "missing"}`` when the package was built without
        swagger_meta.json (pre-v0.6 snapshot).
        """
        meta = _load_swagger_meta()
        if meta is None:
            return make_error(
                "not_found",
                (
                    "swagger_meta.json not bundled — rebuild the package "
                    "from a snapshot produced by parser/parse_swagger.py "
                    "(which emits this file) or copy it from parser/ into "
                    "ozon-mcp/src/ozon_mcp/data/."
                ),
                # Backwards-compat: legacy callers branch on error == "missing".
                error="missing",
            )
        return meta
