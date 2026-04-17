"""Subscription pre-check ("gate") unit tests.

Covers the pure helper `tier_sufficient` and the structured
`subscription_gate` response path in the execution tool. The tool path
uses the real knowledge YAML bundled with the package, so curated
``subscription_overrides.yaml`` entries act as the fixture.
"""

from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP

from ozon_mcp import state
from ozon_mcp.knowledge.loader import load_knowledge
from ozon_mcp.schema import load_catalog
from ozon_mcp.tools import execution
from ozon_mcp.tools.execution import tier_sufficient
from ozon_mcp.transport.ratelimit import RateLimitRegistry
from ozon_mcp.transport.seller import SellerClient

# ── pure helper: tier_sufficient ─────────────────────────────────────────────


def test_equal_tier_is_sufficient() -> None:
    assert tier_sufficient("PREMIUM_PRO", "PREMIUM_PRO") is True


def test_lower_tier_is_not_sufficient() -> None:
    assert tier_sufficient("PREMIUM_PLUS", "PREMIUM_PRO") is False


def test_higher_tier_is_sufficient() -> None:
    assert tier_sufficient("PREMIUM_PRO", "PREMIUM_PLUS") is True


def test_unknown_cabinet_tier_allowed() -> None:
    # No cabinet info → let Ozon decide.
    assert tier_sufficient(None, "PREMIUM_PRO") is True


def test_unknown_required_tier_allowed() -> None:
    # No curated requirement → don't gate.
    assert tier_sufficient("PREMIUM_PLUS", None) is True
    assert tier_sufficient("PREMIUM_PLUS", "unknown") is True


def test_unrecognised_tier_names_do_not_block() -> None:
    # Future-proofing: if Ozon invents a new tier we don't model,
    # fall back to permissive.
    assert tier_sufficient("GALAXY_BRAIN", "PREMIUM_PRO") is True
    assert tier_sufficient("PREMIUM_PRO", "ULTRA") is True


def test_premium_lite_alias_equals_lite() -> None:
    # seller/info returns PREMIUM_LITE; we model LITE as the same slot.
    assert tier_sufficient("PREMIUM_LITE", "LITE") is True
    assert tier_sufficient("PREMIUM_LITE", "PREMIUM") is False


def test_tier_names_are_case_insensitive() -> None:
    assert tier_sufficient("premium_pro", "PREMIUM_PLUS") is True


# ── tool path: ozon_call_method returns subscription_gate before HTTP ────────


def _parse(call_result) -> dict:
    content_list = call_result[0]
    return json.loads(content_list[0].text)


@pytest.fixture(autouse=True)
def _reset_state():
    state.reset()
    yield
    state.reset()


async def test_gate_refuses_premium_pro_method_on_premium_plus_cabinet(
    httpx_mock,
) -> None:
    catalog = load_catalog()
    knowledge = load_knowledge()
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None, knowledge=knowledge)

    # ProductPricesDetails has curated required_tier=PREMIUM_PRO; calling it
    # with a PREMIUM_PLUS cabinet must return subscription_gate and MUST NOT
    # issue an HTTP request.
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "ProductPricesDetails",
                "params": {"skus": [123]},
                "cabinet_tier": "PREMIUM_PLUS",
            },
        )
    )
    assert result["error"] == "subscription_gate"
    assert result["required_tier"] == "PREMIUM_PRO"
    assert result["cabinet_tier"] == "PREMIUM_PLUS"
    assert result["http_call_skipped"] is True
    assert len(httpx_mock.get_requests()) == 0
    await seller.aclose()


async def test_gate_allows_call_when_cabinet_tier_is_unknown(
    httpx_mock,
) -> None:
    catalog = load_catalog()
    knowledge = load_knowledge()
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None, knowledge=knowledge)

    # No cabinet_tier argument and no cached state → gate should NOT engage.
    # We expect the call to proceed through validation (which will reject
    # the empty body); the key assertion is that it is not a subscription_gate.
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "ProductPricesDetails",
                "params": {},
            },
        )
    )
    assert result.get("error") != "subscription_gate"
    # 0 or 1 HTTP requests — either validation blocked locally or the
    # request was attempted and mocked off. Either way, not gated.
    await seller.aclose()


async def test_gate_does_not_fire_for_unknown_requirement(
    httpx_mock,
) -> None:
    """Methods without curated subscription_overrides must fall through."""
    catalog = load_catalog()
    knowledge = load_knowledge()
    rate_limits = RateLimitRegistry(kb=knowledge)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None, knowledge=knowledge)

    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v1/seller/info",
        json={"subscription": {"type": "PREMIUM_LITE", "is_premium": False}},
    )
    # SellerAPI_SellerInfo is a read method with no curated override — it
    # must not be blocked regardless of cabinet tier.
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "SellerAPI_SellerInfo",
                "params": {},
                "cabinet_tier": "LITE",
            },
        )
    )
    assert result.get("error") != "subscription_gate"
    assert result.get("ok") is True
    await seller.aclose()


async def test_describe_surfaces_pre_check_available_true_for_curated() -> None:
    """ozon_describe_method must signal pre_check_available=True for
    methods with a concrete curated subscription requirement."""
    from ozon_mcp.knowledge.loader import load_knowledge
    from ozon_mcp.schema import MethodGraph, load_catalog
    from ozon_mcp.tools.discovery import _serialize_method

    catalog = load_catalog()
    graph = MethodGraph(catalog)
    knowledge = load_knowledge()

    method = catalog.get_by_operation_id("ProductPricesDetails")
    assert method is not None
    serialised = _serialize_method(method, graph, knowledge)
    sub = serialised.get("subscription")
    assert sub is not None
    assert sub["required"] == "PREMIUM_PRO"
    assert sub["pre_check_available"] is True


async def test_describe_marks_pre_check_unavailable_for_unknown() -> None:
    """When required_tier is 'unknown' the agent cannot pre-check."""
    from ozon_mcp.knowledge.loader import load_knowledge
    from ozon_mcp.schema import MethodGraph, load_catalog
    from ozon_mcp.tools.discovery import _serialize_method

    catalog = load_catalog()
    graph = MethodGraph(catalog)
    knowledge = load_knowledge()

    method = catalog.get_by_operation_id("ProductAPI_GetProductRatingBySku")
    assert method is not None
    serialised = _serialize_method(method, graph, knowledge)
    sub = serialised.get("subscription")
    assert sub is not None
    assert sub["required"] == "unknown"
    assert sub["pre_check_available"] is False
