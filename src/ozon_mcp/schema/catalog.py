"""In-memory index of all Ozon API methods."""

from __future__ import annotations

from typing import Any, Literal

from ozon_mcp.schema.extractor import Method, MethodExtractor
from ozon_mcp.schema.loader import load_perf_spec, load_seller_spec
from ozon_mcp.schema.resolver import RefResolver

# Tags that are documentation noise rather than real API sections.
SKIP_TAGS = frozenset(
    {
        "Introduction",
        "Getting started",
        "Auth",
        "OAuth-token",
        "Environment",
        "Process",
        "BetaIntro",
        "OzonLogistics",
        "Intro",
        "Token",
        "Limits",
        "News",
    }
)

ApiLabel = Literal["seller", "performance"]


class Catalog:
    """Lookup-friendly view over the full set of extracted methods."""

    def __init__(self, methods: list[Method]) -> None:
        self.methods = methods
        self.by_operation_id: dict[str, Method] = {
            m.operation_id: m for m in methods if m.operation_id
        }
        self.by_path: dict[tuple[str, str, str], Method] = {
            (m.api, m.method, m.path): m for m in methods
        }
        self._sections: dict[tuple[str, str], list[Method]] = {}
        for m in methods:
            self._sections.setdefault((m.api, m.section), []).append(m)
        self._tags: dict[tuple[str, str], list[Method]] = {}
        for m in methods:
            self._tags.setdefault((m.api, m.tag), []).append(m)

    def get_by_operation_id(self, operation_id: str) -> Method | None:
        return self.by_operation_id.get(operation_id)

    def get_by_path(
        self, api: ApiLabel, http_method: str, path: str
    ) -> Method | None:
        return self.by_path.get((api, http_method.upper(), path))

    def find_by_path(self, path: str) -> list[Method]:
        return [m for m in self.methods if m.path == path]

    def list_sections(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for (api, section), methods in self._sections.items():
            result.append(
                {
                    "api": api,
                    "section": section,
                    "tag": methods[0].tag,
                    "count": len(methods),
                }
            )
        return sorted(result, key=lambda x: (x["api"], x["section"]))

    def get_section(self, query: str) -> list[Method]:
        q = query.lower()
        seen: set[str] = set()
        out: list[Method] = []
        for m in self.methods:
            if m.operation_id in seen:
                continue
            if q in m.section.lower() or q in m.tag.lower():
                out.append(m)
                seen.add(m.operation_id)
        return out

    @property
    def total_methods(self) -> int:
        return len(self.methods)


def load_catalog() -> Catalog:
    """Build the global Catalog from bundled swagger files."""
    methods: list[Method] = []
    for spec, api_label in (
        (load_seller_spec(), "seller"),
        (load_perf_spec(), "performance"),
    ):
        api: ApiLabel = api_label  # type: ignore[assignment]
        resolver = RefResolver(spec)
        extractor = MethodExtractor(resolver, api)
        tags_display = {
            t.get("name", ""): t.get("x-displayName", t.get("name", ""))
            for t in spec.get("tags", [])
            if isinstance(t, dict)
        }
        for path, path_item in (spec.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            for http_method, op in path_item.items():
                if http_method not in ("get", "post", "put", "delete", "patch"):
                    continue
                if not isinstance(op, dict):
                    continue
                op_tags = op.get("tags") or ["other"]
                tag = str(op_tags[0]) if op_tags else "other"
                if tag in SKIP_TAGS:
                    continue
                section = str(tags_display.get(tag, tag))
                methods.append(extractor.extract(path, http_method, op, section, tag))
    return Catalog(methods)
