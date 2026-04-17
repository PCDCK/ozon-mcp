"""Method relationship graph extracted from markdown links in descriptions.

Ozon documents methods that go together by linking to each other in the
description text via markdown like `[/v1/warehouse/list](#operation/WarehouseAPI_WarehouseList)`.
We mine those links into a directed graph so agents can ask "what other
methods relate to this one?" without us hand-curating relationships.
"""

from __future__ import annotations

import re

import networkx as nx

from ozon_mcp.schema.catalog import Catalog
from ozon_mcp.schema.extractor import Method

# Matches `[anything](#operation/OperationId)` — Ozon's canonical inter-method link.
_OP_LINK_RE = re.compile(r"\(#operation/([A-Za-z0-9_]+)\)")
# Matches inline path references like `/v1/foo/bar` (with leading slash + version).
_PATH_LINK_RE = re.compile(r"`(/v\d+(?:/[a-zA-Z0-9_\-{}]+)+)`")


class MethodGraph:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._graph: nx.DiGraph = nx.DiGraph()
        self._build()

    def add_workflow_edges(self, workflow_steps: list[list[str]]) -> None:
        """Augment the graph with edges from curated workflow chains.

        Each inner list is an ordered chain of operation_ids that belong to
        one workflow. Methods in a chain become reachable from each other
        with weight=1, regardless of whether they cross-link in their docs.
        """
        for chain in workflow_steps:
            for i, op_id in enumerate(chain):
                if op_id not in self._graph:
                    continue
                for other in chain[i + 1 :]:
                    if other in self._graph:
                        self._graph.add_edge(op_id, other, source="workflow")

    def _build(self) -> None:
        for m in self.catalog.methods:
            if m.operation_id:
                self._graph.add_node(m.operation_id)

        for m in self.catalog.methods:
            if not m.operation_id:
                continue
            targets = self._extract_links(m)
            for target in targets:
                if target == m.operation_id:
                    continue
                if target in self._graph:
                    self._graph.add_edge(m.operation_id, target)

    def _extract_links(self, m: Method) -> set[str]:
        targets: set[str] = set()
        # Operation-level description.
        self._scan_text(m.description or "", targets)
        # Walk request schema (field descriptions hold most cross-references).
        if m.request_schema:
            self._scan_node(m.request_schema, targets)
        for resp in m.response_schemas.values():
            self._scan_node(resp, targets)
        return targets

    def _scan_node(self, node: object, targets: set[str]) -> None:
        if isinstance(node, dict):
            desc = node.get("description")
            if isinstance(desc, str):
                self._scan_text(desc, targets)
            for v in node.values():
                self._scan_node(v, targets)
        elif isinstance(node, list):
            for item in node:
                self._scan_node(item, targets)

    def _scan_text(self, text: str, targets: set[str]) -> None:
        for match in _OP_LINK_RE.finditer(text):
            targets.add(match.group(1))
        for match in _PATH_LINK_RE.finditer(text):
            path = match.group(1)
            for candidate in self.catalog.find_by_path(path):
                if candidate.operation_id:
                    targets.add(candidate.operation_id)

    def related(self, operation_id: str, max_hops: int = 1) -> list[Method]:
        """Return methods linked from *operation_id* up to *max_hops* away.

        Includes both outgoing references (this method links to X) and
        incoming references (X links to this method) — both directions are
        useful for understanding relationships. *max_hops* is clamped to
        [1, 3] to prevent agents from accidentally walking the whole graph.
        """
        if operation_id not in self._graph:
            return []
        max_hops = max(1, min(max_hops, 3))
        seen: set[str] = {operation_id}
        frontier: set[str] = {operation_id}
        for _ in range(max_hops):
            next_frontier: set[str] = set()
            for node in frontier:
                next_frontier.update(self._graph.successors(node))
                next_frontier.update(self._graph.predecessors(node))
            next_frontier -= seen
            seen.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break
        seen.discard(operation_id)
        out: list[Method] = []
        for op_id in seen:
            m = self.catalog.get_by_operation_id(op_id)
            if m is not None:
                out.append(m)
        return out

    @property
    def edge_count(self) -> int:
        return int(self._graph.number_of_edges())

    @property
    def node_count(self) -> int:
        return int(self._graph.number_of_nodes())
