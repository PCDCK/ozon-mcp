"""Auto-extracted subscription tier detection."""


from __future__ import annotations

from ozon_mcp.schema import Catalog
from ozon_mcp.schema.extractor import (
    SUBSCRIPTION_TIERS,
    _detect_subscription_tiers,
    _min_tier,
    _scan_text_for_tiers,
)


def test_text_scan_picks_specific_over_generic() -> None:
    found: set[str] = set()
    _scan_text_for_tiers("доступно для подписки Premium Plus", found)
    assert "PREMIUM_PLUS" in found
    # Plain "Premium" inside "Premium Plus" should NOT double-count.
    assert "PREMIUM" not in found


def test_text_scan_handles_multiple_tiers() -> None:
    found: set[str] = set()
    _scan_text_for_tiers(
        "Без Premium Plus данные ограничены 3 месяцами. С Premium Pro доступен год.",
        found,
    )
    assert found == {"PREMIUM_PLUS", "PREMIUM_PRO"}


def test_text_scan_plain_premium() -> None:
    found: set[str] = set()
    _scan_text_for_tiers("Метод доступен только с подпиской Premium", found)
    assert found == {"PREMIUM"}


def test_text_scan_no_premium_returns_empty() -> None:
    found: set[str] = set()
    _scan_text_for_tiers("Список заказов за период", found)
    assert found == set()


def test_min_tier_picks_lowest() -> None:
    assert _min_tier(["PREMIUM_PRO", "PREMIUM"]) == "PREMIUM"
    assert _min_tier(["PREMIUM_PLUS", "PREMIUM_PRO"]) == "PREMIUM_PLUS"
    assert _min_tier([]) is None


def test_detect_walks_request_and_response_schemas() -> None:
    op = {"description": ""}
    request = {
        "type": "object",
        "properties": {
            "filter": {
                "description": "Доступно только с Premium Plus",
                "type": "object",
            }
        },
    }
    tiers = _detect_subscription_tiers(op, request, {})
    assert "PREMIUM_PLUS" in tiers


def test_analytics_method_has_premium_tiers(catalog: Catalog) -> None:
    """The analytics endpoint mentions all premium tiers in its description."""
    m = catalog.get_by_operation_id("AnalyticsAPI_AnalyticsGetData")
    assert m is not None
    assert "PREMIUM_PLUS" in m.subscription_tiers_mentioned
    assert "PREMIUM_PRO" in m.subscription_tiers_mentioned


def test_at_least_some_methods_have_subscription_hints(catalog: Catalog) -> None:
    with_subs = [m for m in catalog.methods if m.subscription_tiers_mentioned]
    assert len(with_subs) >= 20, "expected dozens of methods to mention Premium tiers"


def test_all_detected_tiers_are_canonical(catalog: Catalog) -> None:
    for m in catalog.methods:
        for t in m.subscription_tiers_mentioned:
            assert t in SUBSCRIPTION_TIERS
