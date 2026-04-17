"""Knowledge base loading and lookups."""

from __future__ import annotations

from ozon_mcp.knowledge import load_knowledge


def test_knowledge_loads_all_files() -> None:
    kb = load_knowledge()
    assert kb.workflows, "at least one workflow should be defined"
    assert kb.rate_limits, "rate limits should be defined"
    assert kb.errors, "error catalog should be populated"
    assert kb.quirks, "quirks should be populated"
    assert kb.examples, "examples should be populated"


def test_workflow_lookup_by_name() -> None:
    kb = load_knowledge()
    wf = kb.get_workflow("sync_orders_fbo")
    assert wf is not None
    assert wf.steps
    assert all(step.operation_id for step in wf.steps)
    assert wf.recommended_db_schema is not None


def test_rate_limit_section_fallback() -> None:
    kb = load_knowledge()
    limit = kb.rate_limit_for(
        "FinanceAPI_FinanceTransactionListV3",
        api="seller",
        section="Финансовые отчёты",
    )
    assert limit is not None
    assert limit.per_minute is not None


def test_quirks_for_known_operation() -> None:
    kb = load_knowledge()
    quirks = kb.quirks_for("FinanceAPI_FinanceTransactionListV3")
    assert quirks
    assert any("месяц" in q.description.lower() or "месяц" in q.title.lower() for q in quirks)


def test_examples_for_known_operation() -> None:
    kb = load_knowledge()
    examples = kb.examples_for("FinanceAPI_FinanceTransactionListV3")
    assert examples
    assert all("filter" in e.request or "page" in e.request for e in examples)


def test_error_lookup_by_code() -> None:
    kb = load_knowledge()
    rate_limit_errors = kb.errors_by_code("429")
    assert rate_limit_errors
    assert any("backoff" in e.fix.lower() for e in rate_limit_errors)


def test_unknown_workflow_returns_none() -> None:
    kb = load_knowledge()
    assert kb.get_workflow("does_not_exist") is None
