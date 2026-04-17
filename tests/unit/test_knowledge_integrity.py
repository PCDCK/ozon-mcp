"""Knowledge-base integrity invariants.

These tests guard against silent breakage when somebody edits a YAML
file without realising the operation_id has been renamed in the
swagger snapshot, or adds a duplicate, or smuggles real production
data into a fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ozon_mcp.knowledge.loader import load_knowledge
from ozon_mcp.schema import load_catalog
from ozon_mcp.schema.extractor import SUBSCRIPTION_TIERS
from ozon_mcp.tools.execution import TIER_HIERARCHY, _normalize_tier


@pytest.fixture(scope="module")
def kb():
    return load_knowledge()


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_all_yaml_files_load_without_errors() -> None:
    """KnowledgeBase loads every YAML file via Pydantic without raising."""
    kb = load_knowledge()
    assert kb.workflows
    assert kb.examples
    assert kb.quirks
    assert kb.rate_limits
    assert kb.subscription_overrides
    assert kb.pagination_patterns
    assert kb.errors
    assert kb.descriptions_overrides


def test_all_subscription_overrides_have_valid_tiers(kb) -> None:
    valid = {"PREMIUM", "PREMIUM_PLUS", "PREMIUM_PRO", "unknown", None}
    bad = [
        s for s in kb.subscription_overrides
        if s.required_tier not in valid
    ]
    assert not bad, f"subscription_overrides with invalid tier: {bad}"


def test_all_subscription_tiers_normalize_into_hierarchy(kb) -> None:
    """Every tier mentioned by an override must normalize to something
    tier_sufficient understands (or be a noop like None/'unknown')."""
    valid_normalized = set(TIER_HIERARCHY)
    for s in kb.subscription_overrides:
        if s.required_tier in (None, "unknown"):
            continue
        norm = _normalize_tier(s.required_tier)
        assert norm in valid_normalized, (
            f"{s.operation_id}: required_tier {s.required_tier!r} normalizes "
            f"to {norm!r}, not in TIER_HIERARCHY"
        )


def test_all_pagination_patterns_have_valid_types(kb) -> None:
    allowed = {"offset_limit", "page_number", "last_id", "cursor", "page_token"}
    for p in kb.pagination_patterns:
        assert p.type in allowed, f"{p.operation_id}: type={p.type!r}"
        assert p.default_limit > 0
        assert p.default_limit <= p.max_limit


def test_pagination_patterns_unique_by_op_id(kb) -> None:
    seen: set[str] = set()
    dupes: list[str] = []
    for p in kb.pagination_patterns:
        if p.operation_id in seen:
            dupes.append(p.operation_id)
        seen.add(p.operation_id)
    assert not dupes, f"duplicate pagination patterns: {dupes}"


def test_all_examples_target_existing_methods(kb, catalog) -> None:
    missing = [
        e.operation_id for e in kb.examples
        if catalog.get_by_operation_id(e.operation_id) is None
    ]
    assert not missing, f"examples for unknown operation_ids: {missing}"


def test_all_workflow_steps_target_existing_methods(kb, catalog) -> None:
    deprecated_ops = {d.operation_id for d in kb.deprecated_methods}
    missing: list[tuple[str, str]] = []
    for wf in kb.workflows:
        for step in wf.steps:
            if step.operation_id in deprecated_ops:
                continue
            if catalog.get_by_operation_id(step.operation_id) is None:
                missing.append((wf.name, step.operation_id))
    assert not missing, f"workflow steps reference unknown operation_ids: {missing}"


def test_all_quirks_target_existing_methods_or_sections(kb, catalog) -> None:
    missing: list[str] = []
    for q in kb.quirks:
        if q.operation_id is None:
            continue
        if catalog.get_by_operation_id(q.operation_id) is None:
            missing.append(q.operation_id)
    assert not missing, f"quirks for unknown operation_ids: {missing}"


def test_all_rate_limits_have_valid_per_minute(kb) -> None:
    for r in kb.rate_limits:
        if r.per_minute is not None:
            assert r.per_minute > 0, f"non-positive per_minute on {r}"


def test_no_real_credentials_in_fixtures() -> None:
    """All product_id / sku in tests/fixtures must use the 990xxxxx prefix."""
    fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures" / "responses"
    suspicious: list[tuple[str, int]] = []
    for path in fixtures_dir.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        # Walk the JSON looking for product_id / sku that are not in the
        # 99000000-99999999 anonymized range.
        data = json.loads(text)
        _walk_for_real_ids(data, path.name, suspicious)
    assert not suspicious, (
        f"Found possible real IDs in fixtures: {suspicious}"
    )


def _walk_for_real_ids(node, file: str, hits: list[tuple[str, int]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                key in ("product_id", "sku", "id", "warehouse_id")
                and isinstance(value, int)
                and not (99_000_000 <= value < 99_999_999)
            ):
                # warehouse_id uses 99100xxx range; product/sku/id use 99000xxx.
                hits.append((file, value))
            _walk_for_real_ids(value, file, hits)
    elif isinstance(node, list):
        for item in node:
            _walk_for_real_ids(item, file, hits)


def test_all_subscription_tiers_in_extractor_set(kb) -> None:
    """Every tier name used in mentions must be one the extractor knows."""
    for s in kb.subscription_overrides:
        if s.required_tier in (None, "unknown"):
            continue
        # PREMIUM_PLUS / PREMIUM_PRO / PREMIUM are in SUBSCRIPTION_TIERS via aliases.
        normalized_for_extractor = (
            "PREMIUM_LITE" if s.required_tier == "LITE" else s.required_tier
        )
        assert normalized_for_extractor in SUBSCRIPTION_TIERS or s.required_tier in {
            "PREMIUM",
            "PREMIUM_PLUS",
            "PREMIUM_PRO",
        }


def test_examples_for_seven_hot_methods_present(kb) -> None:
    """Phase 3 promised one example per hot method — guard against regression."""
    hot = [
        "ProductAPI_GetProductList",
        "ProductAPI_GetProductInfoList",
        "ProductAPI_GetProductInfoPrices",
        "AnalyticsAPI_StocksTurnover",
        "RatingAPI_RatingSummaryV1",
        "ProductAPI_GetProductRatingBySku",
        "PostingAPI_GetFboPostingList",
    ]
    for op_id in hot:
        assert kb.examples_for(op_id), f"no example for {op_id}"
