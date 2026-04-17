"""Business-context quirks + safety_warning coverage."""

from __future__ import annotations

import pytest

from ozon_mcp.knowledge.loader import load_knowledge
from ozon_mcp.schema import load_catalog

BUSINESS_CONTEXT_METHODS = [
    "AnalyticsAPI_StocksTurnover",
    "RatingAPI_RatingSummaryV1",
    "ProductAPI_GetProductRatingBySku",
    "ProductAPI_GetProductInfoPrices",
    "AnalyticsAPI_AnalyticsStocks",
    "PostingAPI_GetFboPostingList",
]


@pytest.fixture(scope="module")
def kb():
    return load_knowledge()


@pytest.fixture(scope="module")
def catalog_with_overrides():
    catalog = load_catalog()
    kb = load_knowledge()
    for o in kb.safety_overrides:
        m = catalog.get_by_operation_id(o.operation_id)
        if m is not None:
            m.safety = o.safety
            m.safety_reason = o.reason
    return catalog


# ── business_context coverage ────────────────────────────────────────


@pytest.mark.parametrize("op_id", BUSINESS_CONTEXT_METHODS)
def test_business_context_present_for_key_methods(kb, op_id: str) -> None:
    quirks = kb.quirks_for(op_id)
    contexts = [q for q in quirks if q.business_context]
    assert contexts, f"{op_id} missing business_context quirk"


@pytest.mark.parametrize("op_id", BUSINESS_CONTEXT_METHODS)
def test_when_to_use_is_non_empty(kb, op_id: str) -> None:
    quirks = kb.quirks_for(op_id)
    with_when = [q for q in quirks if q.when_to_use]
    assert with_when, f"{op_id} missing when_to_use list"
    assert any(len(q.when_to_use) >= 2 for q in with_when), (
        f"{op_id}: when_to_use should have ≥2 entries to be useful"
    )


@pytest.mark.parametrize("op_id", BUSINESS_CONTEXT_METHODS)
def test_common_mistakes_present(kb, op_id: str) -> None:
    quirks = kb.quirks_for(op_id)
    with_mistakes = [q for q in quirks if q.common_mistakes]
    assert with_mistakes, f"{op_id} missing common_mistakes"


# ── safety_warning coverage ──────────────────────────────────────────


def test_every_destructive_method_has_safety_warning(
    kb, catalog_with_overrides
) -> None:
    destructives = [
        m for m in catalog_with_overrides.methods if m.safety == "destructive"
    ]
    missing = []
    for m in destructives:
        quirks = kb.quirks_for(m.operation_id)
        if not any(q.safety_warning for q in quirks):
            missing.append(m.operation_id)
    assert not missing, f"Destructive methods without safety_warning: {missing}"


def test_safety_warning_destructive_text_mentions_double_confirm(kb) -> None:
    quirks = kb.quirks_for("ProductAPI_DeleteProducts")
    warnings = [q.safety_warning for q in quirks if q.safety_warning]
    assert warnings
    assert any(
        "i_understand_this_modifies_data" in w.lower() or "двойн" in w.lower()
        for w in warnings
    )


def test_safety_warning_write_mentions_confirm_write(kb) -> None:
    quirks = kb.quirks_for("ActivateCampaign")
    warnings = [q.safety_warning for q in quirks if q.safety_warning]
    assert warnings
    assert any("confirm_write" in w.lower() for w in warnings)


# ── description overrides coverage ───────────────────────────────────


def test_description_overrides_load_and_apply() -> None:
    kb = load_knowledge()
    assert len(kb.descriptions_overrides) >= 5
    op = "ProductAPI_ProductArchive"
    override = kb.description_override_for(op)
    assert override is not None
    assert "архив" in override.description.lower()
