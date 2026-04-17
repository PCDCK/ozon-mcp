"""Examples coverage for the seven hot-path methods added in Phase 3."""

from __future__ import annotations

import pytest

from ozon_mcp.knowledge.loader import load_knowledge

KEY_METHODS = [
    "ProductAPI_GetProductList",
    "ProductAPI_GetProductInfoList",
    "ProductAPI_GetProductInfoPrices",
    "AnalyticsAPI_StocksTurnover",
    "RatingAPI_RatingSummaryV1",
    "ProductAPI_GetProductRatingBySku",
    "PostingAPI_GetFboPostingList",
]


@pytest.fixture(scope="module")
def kb():
    return load_knowledge()


@pytest.mark.parametrize("op_id", KEY_METHODS)
def test_each_key_method_has_at_least_one_example(kb, op_id: str) -> None:
    examples = kb.examples_for(op_id)
    assert examples, f"{op_id} has no curated example"


@pytest.mark.parametrize("op_id", KEY_METHODS)
def test_examples_have_request_field(kb, op_id: str) -> None:
    for ex in kb.examples_for(op_id):
        assert ex.request is not None, f"{op_id}: example {ex.title!r} lacks request"


def test_get_product_list_has_two_examples() -> None:
    """Spec asked for 2 examples for ProductAPI_GetProductList — basic + filtered."""
    kb = load_knowledge()
    examples = kb.examples_for("ProductAPI_GetProductList")
    assert len(examples) >= 2


def test_examples_for_unknown_method_returns_empty() -> None:
    kb = load_knowledge()
    assert kb.examples_for("TotallyMadeUpOperationDoesNotExist") == []


def test_response_excerpt_present_for_phase3_examples() -> None:
    """The seven Phase-3 examples were authored with response_excerpt — that
    field is the most useful one for Claude when reasoning about a method
    it hasn't seen before."""
    kb = load_knowledge()
    with_excerpt = sum(
        1 for op in KEY_METHODS for ex in kb.examples_for(op)
        if ex.response_excerpt
    )
    assert with_excerpt >= 7
