"""Method safety classification + execution guardrail.

The classifier exists because the audit on 2026-04-12 showed that path-token
heuristics applied at the script level let through Activate/Deactivate calls
on real campaigns. The fix is to put safety in the catalog itself.
"""

from __future__ import annotations

from ozon_mcp.schema import Catalog
from ozon_mcp.schema.extractor import _classify_safety


def test_seller_info_is_read() -> None:
    safety, _ = _classify_safety("POST", "/v1/seller/info", "SellerAPI_SellerInfo")
    assert safety == "read"


def test_product_list_is_read() -> None:
    safety, _ = _classify_safety("POST", "/v3/product/list", "ProductAPI_GetProductList")
    assert safety == "read"


def test_fbo_posting_list_is_read() -> None:
    safety, _ = _classify_safety("POST", "/v2/posting/fbo/list", "PostingAPI_GetFboPostingList")
    assert safety == "read"


def test_finance_transaction_list_is_read() -> None:
    safety, _ = _classify_safety(
        "POST", "/v3/finance/transaction/list", "FinanceAPI_FinanceTransactionListV3"
    )
    assert safety == "read"


def test_activate_campaign_is_write() -> None:
    """REGRESSION for the 2026-04-12 incident."""
    safety, reason = _classify_safety(
        "POST", "/api/client/campaign/{campaignId}/activate", "ActivateCampaign"
    )
    assert safety == "write"
    assert "activate" in reason


def test_deactivate_campaign_is_write() -> None:
    safety, _ = _classify_safety(
        "POST", "/api/client/campaign/{campaignId}/deactivate", "DeactivateCampaign"
    )
    assert safety == "write"


def test_all_sku_promo_activate_is_write() -> None:
    """REGRESSION: All-SKU promo toggle that the incident touched.

    Note: Ozon uses GET for this endpoint despite the side effect. The
    classifier MUST NOT trust the HTTP method blindly.
    """
    safety, _ = _classify_safety(
        "GET", "/api/client/campaign/all_sku_promo/activate", "ActivateAllSkuPromoCampaign"
    )
    assert safety == "write"


def test_all_sku_promo_deactivate_is_write() -> None:
    safety, _ = _classify_safety(
        "GET", "/api/client/campaign/all_sku_promo/deactivate", "DeactivateAllSkuPromoCampaign"
    )
    assert safety == "write"


def test_delete_products_is_destructive() -> None:
    safety, _ = _classify_safety(
        "POST", "/api/client/campaign/{campaignId}/products/delete", "DeleteProducts"
    )
    assert safety == "destructive"


def test_create_campaign_is_write() -> None:
    safety, _ = _classify_safety(
        "POST", "/api/client/campaign/cpc/v2/product", "CreateProductCampaignCPCV2"
    )
    assert safety == "write"


def test_submit_request_is_write() -> None:
    """REGRESSION: /api/client/statistics POST creates an async report and
    consumes Performance API quota. Must NOT be classified as read just
    because the path contains 'statistics'."""
    safety, _ = _classify_safety("POST", "/api/client/statistics", "SubmitRequest")
    assert safety == "write"


def test_vendor_statistics_submit_is_write() -> None:
    safety, _ = _classify_safety(
        "POST", "/api/client/vendors/statistics", "VendorStatisticsSubmitRequest"
    )
    assert safety == "write"


def test_carrots_enable_is_write() -> None:
    safety, _ = _classify_safety(
        "POST", "/api/client/campaign/search_promo/carrots/enable", "ExternalCampaign_BatchEnableCarrots4"
    )
    assert safety == "write"


def test_get_methods_default_to_read() -> None:
    safety, _ = _classify_safety("GET", "/api/client/campaign", "ListCampaigns")
    assert safety == "read"


def test_delete_http_is_destructive() -> None:
    safety, _ = _classify_safety("DELETE", "/some/path", "SomeOperation")
    assert safety == "destructive"


def test_unknown_post_defaults_to_write() -> None:
    """Default-to-write is the safety policy."""
    safety, reason = _classify_safety("POST", "/some/random/endpoint", "RandomOp")
    assert safety == "write"
    assert "default-to-write" in reason or "POST" in reason


def test_cancel_reason_list_is_read_not_destructive() -> None:
    """The cancel-reason endpoint LISTS cancellation reasons, it doesn't cancel.
    Last-segment heuristic must take priority over the 'cancel' substring."""
    safety, _ = _classify_safety("POST", "/v1/posting/fbo/cancel-reason/list", "PostingAPI_GetCancelReason")
    assert safety == "read"


def test_cancel_status_is_read() -> None:
    """`/v1/order/cancel/status` returns the status of a cancel — read, not destructive."""
    safety, _ = _classify_safety("POST", "/v1/order/cancel/status", "OrderAPI_GetCancelStatus")
    assert safety == "read"


def test_no_method_in_catalog_is_unclassified(catalog: Catalog) -> None:
    """All catalog methods get a non-default safety value."""
    unclassified = [m for m in catalog.methods if m.safety not in ("read", "write", "destructive")]
    assert not unclassified


def test_distribution_is_reasonable(catalog: Catalog) -> None:
    """Sanity: read should be the largest bucket, destructive the smallest,
    and the totals should add up to the catalog size."""
    by_safety: dict[str, int] = {"read": 0, "write": 0, "destructive": 0}
    for m in catalog.methods:
        by_safety[m.safety] += 1
    assert sum(by_safety.values()) == catalog.total_methods
    assert by_safety["read"] >= 150
    assert by_safety["destructive"] <= by_safety["write"]
    assert by_safety["destructive"] >= 10  # there are real destructive methods


def test_no_post_with_known_write_verb_is_classified_as_read(catalog: Catalog) -> None:
    """No POST whose path's last segment is a known write/destructive verb may
    be classified as read. This is the regression check for the incident."""
    danger = {
        "activate", "deactivate", "delete", "cancel", "create", "remove",
        "update", "set", "add", "enable", "disable", "submit",
    }
    bad: list[str] = []
    for m in catalog.methods:
        if m.method != "POST" or m.safety != "read":
            continue
        last = m.path.rstrip("/").split("/")[-1].lower()
        last_tokens = set(last.replace("-", "_").split("_"))
        if last_tokens & danger:
            bad.append(f"{m.operation_id} {m.path}")
    assert not bad, f"Found {len(bad)} dangerous-looking methods classified as read: {bad}"
