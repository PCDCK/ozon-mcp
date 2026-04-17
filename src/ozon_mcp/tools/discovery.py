"""Discovery meta-tools: list, search, describe, get_section.

These tools let an agent navigate the entire Ozon API surface without having
all 458 method definitions registered upfront. The agent issues a search or
section listing, then drills into describe_method for the chosen endpoint and
receives a fully-resolved JSON Schema together with related methods, quirks,
rate limit, and examples — everything needed to call the method correctly.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ozon_mcp.knowledge import KnowledgeBase
from ozon_mcp.schema import Catalog, MethodGraph, SearchIndex
from ozon_mcp.schema.errors import make_error
from ozon_mcp.schema.extractor import Method


def register(
    mcp: FastMCP,
    catalog: Catalog,
    search: SearchIndex,
    graph: MethodGraph | None = None,
    knowledge: KnowledgeBase | None = None,
) -> None:
    @mcp.tool()
    def ozon_list_sections() -> dict[str, Any]:
        """List all Ozon API sections (Seller + Performance) with method counts.

        Use this first to orient yourself in the API. Returns sections grouped
        by api ('seller' or 'performance'), each with the human-readable
        section name, the underlying tag, and the number of methods inside.
        """
        sections = catalog.list_sections()
        return {
            "total_methods": catalog.total_methods,
            "seller_sections": [s for s in sections if s["api"] == "seller"],
            "performance_sections": [s for s in sections if s["api"] == "performance"],
        }

    @mcp.tool()
    def ozon_search_methods(
        query: str,
        section: str | None = None,
        api: str | None = None,
        safety: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Full-text search across all Ozon API methods.

        Searches over operation_id, path, summary, description, section, and
        tag using BM25 ranking with field boosting (summary x4, path/op_id x3,
        description x1). Supports Russian and English queries with stemming.

        Args:
            query: free-text query, e.g. "list of postings" or "финансовые транзакции"
            section: optional filter — match by section name or tag (case-insensitive substring)
            api: optional filter — "seller" or "performance"
            safety: optional filter — "read", "write", or "destructive"
            limit: max results to return (default 10)
        """
        results = search.search(query, section=section, api=api, limit=limit * 2)
        if safety:
            results = [r for r in results if r.method.safety == safety]
        results = results[:limit]
        return {
            "query": query,
            "count": len(results),
            "results": [
                {
                    "operation_id": r.method.operation_id,
                    "api": r.method.api,
                    "method": r.method.method,
                    "path": r.method.path,
                    "section": r.method.section,
                    "summary": r.method.summary,
                    "safety": r.method.safety,
                    "score": round(r.score, 3),
                }
                for r in results
            ],
        }

    @mcp.tool()
    def ozon_describe_method(
        operation_id: str | None = None,
        path: str | None = None,
        http_method: str | None = None,
    ) -> dict[str, Any]:
        """Get a complete description of one Ozon API method.

        Returns the method's metadata plus fully-resolved JSON Schema for
        request and responses. All $ref pointers are inlined; oneOf/anyOf/allOf
        combinators are preserved verbatim. When knowledge layer is loaded,
        also includes rate_limit, quirks, examples, and related methods —
        everything an agent needs to call the method correctly.

        Provide either `operation_id` (preferred) OR `path` (+ optional `http_method`).
        """
        method = _resolve_method(catalog, operation_id, path, http_method)
        if isinstance(method, dict):
            # Surface a clean "deprecated/removed" response for known tombstones
            # instead of plain "not found" — existing callers referencing older
            # operation_ids deserve a pointer rather than a 404-style error.
            if knowledge is not None and operation_id:
                tombstone = knowledge.deprecated_for(operation_id)
                if tombstone is not None:
                    out: dict[str, Any] = {
                        "operation_id": tombstone.operation_id,
                        "path": tombstone.path,
                        "method": tombstone.http_method,
                        "deprecated": True,
                        "removed_on": tombstone.removed_on,
                        "deprecation_note": tombstone.note,
                    }
                    if tombstone.replacement:
                        out["replacement_operation_id"] = tombstone.replacement
                    return out
            return method
        return _serialize_method(method, graph, knowledge)

    @mcp.tool()
    def ozon_get_section(query: str) -> dict[str, Any]:
        """List all methods inside a section (by section name or tag).

        Args:
            query: section name or tag, e.g. "FinanceAPI", "Финансовые отчёты", "ProductAPI"
        """
        methods = catalog.get_section(query)
        return {
            "query": query,
            "count": len(methods),
            "methods": [
                {
                    "operation_id": m.operation_id,
                    "api": m.api,
                    "method": m.method,
                    "path": m.path,
                    "summary": m.summary,
                    "section": m.section,
                }
                for m in methods
            ],
        }


def _resolve_method(
    catalog: Catalog,
    operation_id: str | None,
    path: str | None,
    http_method: str | None,
) -> Method | dict[str, Any]:
    if operation_id:
        m = catalog.get_by_operation_id(operation_id)
        if m is None:
            return make_error(
                "not_found",
                f"operation_id {operation_id!r} not found",
                operation_id=operation_id,
                error=f"operation_id {operation_id!r} not found",
            )
        return m
    if path:
        if http_method:
            for api_label in ("seller", "performance"):
                m = catalog.get_by_path(api_label, http_method, path)
                if m is not None:
                    return m
            return make_error(
                "not_found",
                f"{http_method} {path} not found",
                endpoint=path,
                error=f"{http_method} {path} not found",
            )
        matches = catalog.find_by_path(path)
        if len(matches) == 1:
            return matches[0]
        if not matches:
            return make_error(
                "not_found",
                f"path {path!r} not found",
                endpoint=path,
                error=f"path {path!r} not found",
            )
        return make_error(
            "invalid_params",
            f"path {path!r} is ambiguous, specify http_method",
            endpoint=path,
            error=f"path {path!r} is ambiguous, specify http_method",
            payload={
                "candidates": [
                    {"method": m.method, "operation_id": m.operation_id} for m in matches
                ],
            },
            # Backwards-compat for existing callers reading `candidates` at top level.
            candidates=[
                {"method": m.method, "operation_id": m.operation_id} for m in matches
            ],
        )
    return make_error(
        "invalid_params",
        "provide operation_id or path",
        error="provide operation_id or path",
    )


def _serialize_method(
    m: Method,
    graph: MethodGraph | None,
    knowledge: KnowledgeBase | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "operation_id": m.operation_id,
        "api": m.api,
        "method": m.method,
        "path": m.path,
        "section": m.section,
        "tag": m.tag,
        "summary": m.summary,
        "description": m.description,
        "auth": m.auth_type,
        "parameters": m.parameters,
        "request_schema": m.request_schema,
        "response_schemas": m.response_schemas,
        "response_descriptions": m.response_descriptions,
    }

    out["safety"] = m.safety
    if m.safety_reason:
        out["safety_reason"] = m.safety_reason
    if m.safety in ("write", "destructive"):
        out["safety_warning"] = (
            "This method modifies data. ozon_call_method will refuse to invoke it "
            "without confirm_write=True"
            + (" AND i_understand_this_modifies_data=True" if m.safety == "destructive" else "")
            + "."
        )

    if m.deprecated:
        out["deprecated"] = True
        if m.deprecation_note:
            out["deprecation_note"] = m.deprecation_note

    # ── Subscription info: auto-extracted + curated override ───────────────
    # The `subscription` block may include up to three fields:
    #   required        — curated hard requirement (or null = works on every tier)
    #   source          — where `required` came from (swagger/empirical/curated/…)
    #   tiers_mentioned — all tier names auto-pulled from the swagger text
    #   min_tier_hint   — lowest tier from tiers_mentioned (fallback signal)
    #
    # Consumers should prefer `required` when it is present and not "unknown".
    subscription_block: dict[str, Any] = {}
    if m.subscription_tiers_mentioned:
        subscription_block["tiers_mentioned"] = m.subscription_tiers_mentioned
        subscription_block["min_tier_hint"] = m.subscription_min_tier
    if knowledge is not None and m.operation_id:
        override = knowledge.subscription_for(m.operation_id)
        if override is not None:
            subscription_block["required"] = override.required_tier
            subscription_block["source"] = override.source
            if override.note:
                subscription_block["required_note"] = override.note
    if subscription_block:
        # `pre_check_available` tells callers whether the server can
        # reject the call BEFORE issuing the HTTP request (i.e. we have a
        # curated, concrete requirement). When False, a call may still be
        # rejected by Ozon — we just don't know that up front.
        required_value = subscription_block.get("required")
        subscription_block["pre_check_available"] = (
            required_value is not None and required_value != "unknown"
        )
        subscription_block.setdefault(
            "note",
            "`required` is curated (swagger + sync-log evidence). "
            "`tiers_mentioned` + `min_tier_hint` are auto-extracted from "
            "method text — use them only when `required` is absent or "
            "\"unknown\". When `pre_check_available` is true, "
            "ozon_call_method will refuse the call locally if the "
            "cabinet tier is insufficient. Call ozon_get_subscription_status "
            "to learn the current account tier.",
        )
        out["subscription"] = subscription_block

    # Tombstone for methods that were in older Ozon spec snapshots but have
    # been removed upstream. Surface them as deprecated rather than 404.
    if knowledge is not None and m.operation_id:
        tombstone = knowledge.deprecated_for(m.operation_id)
        if tombstone is not None:
            out["deprecated"] = True
            out["deprecation_note"] = tombstone.note or "Removed from Ozon spec."
            out["removed_on"] = tombstone.removed_on
            if tombstone.replacement:
                out["replacement_operation_id"] = tombstone.replacement

    if knowledge is not None and m.operation_id:
        rate_limit = knowledge.rate_limit_for(m.operation_id, api=m.api, section=m.section)
        if rate_limit is not None:
            out["rate_limit"] = rate_limit.model_dump()

        quirks = knowledge.quirks_for(m.operation_id)
        if quirks:
            out["quirks"] = [q.model_dump() for q in quirks]

        examples = knowledge.examples_for(m.operation_id)
        if examples:
            out["examples"] = [e.model_dump() for e in examples]

        errors = knowledge.errors_for(m.operation_id)
        if errors:
            out["specific_errors"] = [e.model_dump() for e in errors]

    if graph is not None and m.operation_id:
        related = graph.related(m.operation_id, max_hops=1)
        if related:
            out["related_methods"] = [
                {
                    "operation_id": r.operation_id,
                    "summary": r.summary,
                    "path": r.path,
                    "api": r.api,
                }
                for r in related
            ]

    return out
