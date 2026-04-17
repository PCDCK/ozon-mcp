"""Unit tests for scripts/generate_subscription_overrides.py.

Uses a synthetic mini-spec fixture so the tests stay stable when the
real bundled Ozon swagger gets refreshed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import generate_subscription_overrides as gen  # noqa: E402


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Build a tiny seller-like + perf-like swagger pair for the generator."""
    seller = {
        "info": {"version": "2.1"},
        "paths": {
            "/v1/analytics/data": {
                "post": {
                    "operationId": "AnalyticsAPI_AnalyticsGetData",
                    "summary": "Данные аналитики",
                    "description": (
                        "Для продавцов с подпиской [Premium Plus]"
                        "(https://example) или [Premium Pro](https://example) "
                        "доступен полный год истории."
                    ),
                    "tags": ["AnalyticsAPI"],
                }
            },
            "/v1/product/prices/details": {
                "post": {
                    "operationId": "ProductPricesDetails",
                    "summary": "Цены покупателя",
                    "description": (
                        "Доступно для продавцов с подпиской Premium Pro."
                    ),
                    "tags": ["ProductAPI"],
                }
            },
            "/v1/question/list": {
                "post": {
                    "operationId": "Question_List",
                    "summary": "Список вопросов",
                    "description": (
                        "Доступно для продавцов с подпиской Premium Plus."
                    ),
                    "tags": ["QuestionAnswer"],
                }
            },
            "/v1/report/products/create": {
                "post": {
                    "operationId": "ReportAPI_CreateCompanyProductsReport",
                    "summary": "Создать отчёт",
                    "description": (
                        "Колонки: цена Premium для покупателей."
                    ),
                    "tags": ["ReportAPI"],
                }
            },
            "/v1/product/list": {
                "post": {
                    "operationId": "ProductAPI_ProductList",
                    "summary": "Список товаров",
                    "description": "Без подписки — работает всегда.",
                    "tags": ["ProductAPI"],
                }
            },
        },
    }
    perf = {"info": {"version": "2.0"}, "paths": {}}
    seller_path = tmp_path / "seller.json"
    perf_path = tmp_path / "perf.json"
    seller_path.write_text(json.dumps(seller))
    perf_path.write_text(json.dumps(perf))
    return seller_path, perf_path


def test_strictest_tier_wins() -> None:
    """Mentioning both Premium Plus and Premium Pro must pick PREMIUM_PRO
    (first match in our ordered TIER_PATTERNS)."""
    text = (
        "Премиум-методы. Для продавцов с подпиской Premium Plus или "
        "Premium Pro доступно больше метрик."
    )
    tier, snippet = gen._classify(text)
    assert tier == "PREMIUM_PRO"
    assert snippet  # non-empty


def test_premium_plus_detected_when_only_plus() -> None:
    tier, _ = gen._classify("Доступно для продавцов с подпиской Premium Plus.")
    assert tier == "PREMIUM_PLUS"


def test_premium_only_when_no_plus_or_pro() -> None:
    tier, _ = gen._classify("Цена Premium для покупателей.")
    assert tier == "PREMIUM"


def test_no_mention_returns_none() -> None:
    tier, _ = gen._classify("Обычный метод без упоминания подписок.")
    assert tier is None


def test_hyphen_underscore_tolerant() -> None:
    assert gen._classify("Premium-Pro exclusive")[0] == "PREMIUM_PRO"
    assert gen._classify("premium_plus only")[0] == "PREMIUM_PLUS"


def test_end_to_end_run_produces_expected_matches(tmp_path: Path) -> None:
    seller_path, perf_path = _write_fixture(tmp_path)
    main = tmp_path / "subscription_overrides.yaml"
    auto = tmp_path / "auto.yaml"
    report = tmp_path / "report.txt"

    summary = gen.run(
        seller_path=seller_path,
        perf_path=perf_path,
        main_yaml=main,
        auto_yaml=auto,
        report_txt=report,
        apply=True,
    )

    # 5 ops in the fixture, 4 mention a tier.
    assert summary["total_scanned"] == 5
    assert summary["auto_matches"] == 4
    assert summary["main_yaml_updated"] is True

    # Read back the merged main YAML.
    rows = yaml.safe_load(main.read_text())
    op_to_tier = {r["operation_id"]: r["required_tier"] for r in rows}
    assert op_to_tier["AnalyticsAPI_AnalyticsGetData"] == "PREMIUM_PRO"
    assert op_to_tier["ProductPricesDetails"] == "PREMIUM_PRO"
    assert op_to_tier["Question_List"] == "PREMIUM_PLUS"
    assert op_to_tier["ReportAPI_CreateCompanyProductsReport"] == "PREMIUM"
    assert "ProductAPI_ProductList" not in op_to_tier  # no mention → skipped


def test_curated_entries_are_preserved_on_rerun(tmp_path: Path) -> None:
    seller_path, perf_path = _write_fixture(tmp_path)
    main = tmp_path / "subscription_overrides.yaml"
    auto = tmp_path / "auto.yaml"
    report = tmp_path / "report.txt"

    # Seed the main file with a curated entry that differs from what the
    # regex would choose — and a null (no-gate) entry.
    main.write_text(
        yaml.safe_dump(
            [
                {
                    "operation_id": "AnalyticsAPI_AnalyticsGetData",
                    "endpoint": "/v1/analytics/data",
                    "required_tier": "PREMIUM_PLUS",
                    "source": "swagger+curated",
                    "note": "Curator override — PLUS is the real hard gate.",
                },
                {
                    "operation_id": "CustomEndpoint",
                    "required_tier": None,
                    "source": "empirical",
                    "note": "Known to work on every tier.",
                },
            ],
            allow_unicode=True,
        )
    )

    gen.run(
        seller_path=seller_path,
        perf_path=perf_path,
        main_yaml=main,
        auto_yaml=auto,
        report_txt=report,
        apply=True,
    )

    rows = yaml.safe_load(main.read_text())
    op_to_row = {r["operation_id"]: r for r in rows}

    # Curated row survives verbatim.
    analytics = op_to_row["AnalyticsAPI_AnalyticsGetData"]
    assert analytics["required_tier"] == "PREMIUM_PLUS"
    assert analytics["source"] == "swagger+curated"

    # The other curated row (not in fixture) also survives.
    custom = op_to_row["CustomEndpoint"]
    assert custom["source"] == "empirical"
    assert custom["required_tier"] is None

    # The three other auto matches are still present.
    assert op_to_row["ProductPricesDetails"]["source"] == "swagger"
    assert op_to_row["Question_List"]["source"] == "swagger"


def test_previous_auto_entries_get_rewritten(tmp_path: Path) -> None:
    seller_path, perf_path = _write_fixture(tmp_path)
    main = tmp_path / "subscription_overrides.yaml"
    auto = tmp_path / "auto.yaml"
    report = tmp_path / "report.txt"

    # Pretend the previous generator classified ProductPricesDetails as
    # PREMIUM by mistake. A fresh run MUST replace it with PREMIUM_PRO.
    main.write_text(
        yaml.safe_dump(
            [
                {
                    "operation_id": "ProductPricesDetails",
                    "endpoint": "/v1/product/prices/details",
                    "required_tier": "PREMIUM",
                    "source": "swagger",
                    "note": "old (wrong) detection",
                }
            ],
            allow_unicode=True,
        )
    )

    gen.run(
        seller_path=seller_path,
        perf_path=perf_path,
        main_yaml=main,
        auto_yaml=auto,
        report_txt=report,
        apply=True,
    )
    rows = yaml.safe_load(main.read_text())
    op_to_row = {r["operation_id"]: r for r in rows}
    assert op_to_row["ProductPricesDetails"]["required_tier"] == "PREMIUM_PRO"


def test_report_contains_counts(tmp_path: Path) -> None:
    seller_path, perf_path = _write_fixture(tmp_path)
    main = tmp_path / "subscription_overrides.yaml"
    auto = tmp_path / "auto.yaml"
    report = tmp_path / "report.txt"

    gen.run(
        seller_path=seller_path,
        perf_path=perf_path,
        main_yaml=main,
        auto_yaml=auto,
        report_txt=report,
        apply=False,
    )
    text = report.read_text()
    assert "Total operations scanned" in text
    assert "PREMIUM_PRO" in text
    assert "PREMIUM_PLUS" in text
