"""Search quality regression — golden query → expected operation_id pairs.

Hand-curated query set spanning Russian and English, common BI scenarios,
typo-light variations, and section-specific lookups. Three buckets:

  - GOLDEN_TOP1: top result must be exactly this op (strict canonical)
  - GOLDEN_TOP1_ANY: top result must be any of N acceptable ops
  - GOLDEN_TOP_N: expected op must appear in top N (recall test)

Some queries are inherently ambiguous (e.g. "товары" matches dozens of
product methods). Those live in TOP1_ANY or TOP_N to acknowledge that
multiple methods are equally correct answers.
"""



from __future__ import annotations

import pytest

from ozon_mcp.schema import SearchIndex

# Strict precision@1 — there is one canonical answer for each query.
GOLDEN_TOP1: list[tuple[str, str]] = [
    # Russian — phrase exactly matches the canonical method's summary
    ("список товаров", "ProductAPI_GetProductList"),
    ("список кампаний", "ListCampaigns"),
    # English — short, unambiguous
    ("seller info", "SellerAPI_SellerInfo"),
    ("list campaigns", "ListCampaigns"),
    ("performance limits", "GetLimitsList"),
    # Specific operation_id substrings (CamelCase queries)
    ("FinanceTransactionList", "FinanceAPI_FinanceTransactionListV3"),
    ("AnalyticsGetData", "AnalyticsAPI_AnalyticsGetData"),
    ("GetFboPostingList", "PostingAPI_GetFboPostingList"),
    ("SellerInfo", "SellerAPI_SellerInfo"),
    # Path-style queries
    ("/v3/finance/transaction/list", "FinanceAPI_FinanceTransactionListV3"),
    ("/v3/product/list", "ProductAPI_GetProductList"),
    ("/v2/posting/fbo/list", "PostingAPI_GetFboPostingList"),
    ("/v1/seller/info", "SellerAPI_SellerInfo"),
    ("/v1/analytics/data", "AnalyticsAPI_AnalyticsGetData"),
]


# Lenient precision@1 — top result must be ANY of the acceptable canonical ops.
GOLDEN_TOP1_ANY: list[tuple[str, set[str]]] = [
    (
        "транзакции финансы",
        {
            "FinanceAPI_FinanceTransactionListV3",
            "FinanceAPI_FinanceTransactionTotalV3",
        },
    ),
    (
        "финансовые отчёты",
        {
            "FinanceAPI_FinanceTransactionListV3",
            "FinanceAPI_FinanceTransactionTotalV3",
            "ReportAPI_GetCompensationReport",
            "ReportAPI_GetDecompensationReport",
            "FinanceAPI_FinanceCashFlowStatementList",
            "ReportAPI_CreateMutualSettlementReport",
            "FinanceCommissionProductsReport",
            "FinanceAPI_FinanceRealizationListByDay",
            "FinanceAPI_FinanceRealizationListV2",
        },
    ),
    (
        "цены товаров",
        {
            "ProductAPI_GetProductInfoPrices",
            "ProductAPI_ImportProductsPrices",
            "ProductAPI_GetProductPrice",
            "PricingProductsList",
            "pricing_items-list",
        },
    ),
    (
        "список отзывов",
        {
            "ReviewAPI_ReviewList",
            "ReviewAPI_CommentList",
        },
    ),
    (
        "review list",
        {
            "ReviewAPI_ReviewList",
            "ReviewAPI_CommentList",
        },
    ),
    (
        "список вопросов",
        {
            "Question_List",
            "QuestionAnswer_List",
        },
    ),
    (
        "список складов",
        {
            "WarehouseListV2",
            "WarehouseFboSellerList",
            "SupplyDraftAPI_DraftGetWarehouseFboList",
        },
    ),
    (
        "list transactions",
        {
            "FinanceAPI_FinanceTransactionListV3",
            "FinanceAPI_FinanceTransactionTotalV3",
        },
    ),
    (
        "analytics data",
        {
            "AnalyticsAPI_AnalyticsGetData",
            "AnalyticsTurnoverStocks",
        },
    ),
]


# Recall@N — expected method must appear in top N.
# Queries that are short and vague (e.g. "fbs postings") use top N=10
# because Ozon has a dozen methods around any single concept and the
# canonical one is rarely top-1 without additional context words.
GOLDEN_TOP_N: list[tuple[str, str, int]] = [
    ("отправления fbo", "PostingAPI_GetFboPostingList", 10),
    ("отправления fbs", "PostingAPI_GetFbsPostingListV3", 15),
    ("fbo postings", "PostingAPI_GetFboPostingList", 10),
    ("fbs postings", "PostingAPI_GetFbsPostingListV3", 15),
    ("список отправлений", "PostingAPI_GetFboPostingList", 10),
    ("информация о товаре", "ProductAPI_GetProductInfoList", 10),
    ("product info", "ProductAPI_GetProductInfoList", 10),
    ("product list", "ProductAPI_GetProductList", 5),
    ("остатки на складе", "ProductInfoWarehouseStocks", 5),
    ("warehouse stocks", "ProductInfoWarehouseStocks", 5),
    ("товары с остатками", "ProductInfoWarehouseStocks", 5),
    ("список отчётов", "ListReports", 5),
]


def test_search_precision_at_1(search_index: SearchIndex) -> None:
    """Strict precision@1: top result must be exactly the expected operation."""
    failures: list[str] = []
    for query, expected in GOLDEN_TOP1:
        results = search_index.search(query, limit=1)
        if not results:
            failures.append(f"  '{query}' → NO RESULTS (expected {expected})")
            continue
        top = results[0].method.operation_id
        if top != expected:
            failures.append(f"  '{query}' → got {top}, expected {expected}")
    total = len(GOLDEN_TOP1)
    passed = total - len(failures)
    precision = passed / total
    print(f"\nprecision@1 (strict): {passed}/{total} = {precision:.0%}", end="")
    if failures:
        print("\nFailures:\n" + "\n".join(failures))
    assert precision >= 0.85, f"precision@1 dropped to {precision:.0%}, threshold 85%"


def test_search_precision_at_1_any(search_index: SearchIndex) -> None:
    """Lenient precision@1: top result must be any of the acceptable ops."""
    failures: list[str] = []
    for query, acceptable in GOLDEN_TOP1_ANY:
        results = search_index.search(query, limit=1)
        if not results:
            failures.append(f"  '{query}' → NO RESULTS")
            continue
        top = results[0].method.operation_id
        if top not in acceptable:
            failures.append(
                f"  '{query}' → got {top}, expected any of {sorted(acceptable)[:3]}..."
            )
    total = len(GOLDEN_TOP1_ANY)
    passed = total - len(failures)
    precision = passed / total
    print(f"\nprecision@1 (any): {passed}/{total} = {precision:.0%}", end="")
    if failures:
        print("\nFailures:\n" + "\n".join(failures))
    assert precision >= 0.85, f"precision@1 (any) dropped to {precision:.0%}"


def test_search_top_n_recall(search_index: SearchIndex) -> None:
    """Recall@N: expected method must show up in top N results."""
    failures: list[str] = []
    for query, expected, n in GOLDEN_TOP_N:
        results = search_index.search(query, limit=n)
        ops = [r.method.operation_id for r in results]
        if expected not in ops:
            failures.append(f"  '{query}' → {expected} not in top {n}: {ops[:5]}")
    total = len(GOLDEN_TOP_N)
    passed = total - len(failures)
    recall = passed / total
    print(f"\nrecall@N: {passed}/{total} = {recall:.0%}", end="")
    if failures:
        print("\nFailures:\n" + "\n".join(failures))
    assert recall >= 0.85, f"recall@N dropped to {recall:.0%}"


@pytest.mark.parametrize("limit", [5, 10, 20])
def test_search_returns_at_most_limit(search_index: SearchIndex, limit: int) -> None:
    results = search_index.search("товары", limit=limit)
    assert len(results) <= limit


def test_camelcase_tokenizer_finds_finance_transaction(search_index: SearchIndex) -> None:
    """Just typing 'finance transaction' should find FinanceTransactionListV3
    even though that exact string is buried inside a CamelCase op_id."""
    results = search_index.search("finance transaction", limit=5)
    op_ids = [r.method.operation_id for r in results]
    assert any("FinanceTransaction" in op for op in op_ids)
