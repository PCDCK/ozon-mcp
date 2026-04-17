"""ozon_call_method tool tests with fully mocked transport."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from ozon_mcp.schema import load_catalog
from ozon_mcp.tools import execution
from ozon_mcp.transport.ratelimit import RateLimitRegistry
from ozon_mcp.transport.seller import SellerClient


def _parse(call_result) -> dict:
    content_list = call_result[0]
    return json.loads(content_list[0].text)


async def test_execution_tool_validates_params(httpx_mock) -> None:
    catalog = load_catalog()
    rate_limits = RateLimitRegistry(kb=None)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None)

    # Missing required params (page, page_size) → client-side validation fails.
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "FinanceAPI_FinanceTransactionListV3",
                "params": {},
            },
        )
    )
    assert result["error"] == "OzonClientValidationError"
    assert len(httpx_mock.get_requests()) == 0
    await seller.aclose()


async def test_execution_tool_unknown_operation() -> None:
    catalog = load_catalog()
    rate_limits = RateLimitRegistry(kb=None)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None)

    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {"operation_id": "DoesNotExist", "params": {}},
        )
    )
    assert result["error"] == "NotFound"
    await seller.aclose()


async def test_execution_tool_missing_credentials_for_api() -> None:
    catalog = load_catalog()
    mcp = FastMCP("test")
    # Only seller client, no performance.
    rate_limits = RateLimitRegistry(kb=None)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    execution.register(mcp, catalog, seller, None)

    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "SubmitRequest",
                "params": {"campaigns": ["1"]},
                "confirm_write": True,
            },
        )
    )
    assert result["error"] == "MissingCredentials"
    await seller.aclose()


async def test_execution_refuses_write_without_confirm(httpx_mock) -> None:
    """REGRESSION for the 2026-04-12 incident: write methods must require explicit
    confirmation. Even if the agent constructs valid params for a write method,
    ozon_call_method must refuse without confirm_write=True."""
    catalog = load_catalog()
    rate_limits = RateLimitRegistry(kb=None)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None)

    # ActivateCampaign is the canonical incident method
    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {"operation_id": "ActivateCampaign", "params": {}},
        )
    )
    assert result["error"] == "WriteRequiresConfirmation"
    assert result["safety"] == "write"
    # Critically: zero HTTP requests went out.
    assert len(httpx_mock.get_requests()) == 0
    await seller.aclose()


async def test_execution_refuses_destructive_with_only_one_confirm(httpx_mock) -> None:
    """Destructive methods need BOTH flags. Single confirm_write is not enough."""
    catalog = load_catalog()
    rate_limits = RateLimitRegistry(kb=None)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None)

    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "DeleteProducts",
                "params": {"sku": ["1"]},
                "confirm_write": True,
            },
        )
    )
    assert result["error"] == "DestructiveRequiresDoubleConfirmation"
    assert result["safety"] == "destructive"
    assert len(httpx_mock.get_requests()) == 0
    await seller.aclose()


async def test_execution_destructive_with_double_confirm_bypasses_guard() -> None:
    """With BOTH flags set, the guard does not block — execution proceeds
    to the next step (which may then fail for unrelated reasons like
    missing credentials, but not because of the safety guard)."""
    catalog = load_catalog()
    mcp = FastMCP("test")
    # No clients passed → expect MissingCredentials error AFTER the guard.
    execution.register(mcp, catalog, None, None)

    delete_method = catalog.get_by_operation_id("DeleteProducts")
    assert delete_method is not None
    assert delete_method.safety == "destructive"

    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "DeleteProducts",
                "params": {"sku": ["1"]},
                "confirm_write": True,
                "i_understand_this_modifies_data": True,
            },
        )
    )
    # The guard let us through; downstream we hit MissingCredentials.
    assert result["error"] == "MissingCredentials"


async def test_execution_read_methods_work_without_confirm(httpx_mock) -> None:
    """Read methods don't need any confirm flag."""
    catalog = load_catalog()
    rate_limits = RateLimitRegistry(kb=None)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None)

    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v1/seller/info",
        method="POST",
        json={"company": {}, "subscription": {"is_premium": True}},
    )

    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {"operation_id": "SellerAPI_SellerInfo", "params": {}},
        )
    )
    assert result.get("ok") is True
    await seller.aclose()


async def test_execution_tool_happy_path(httpx_mock) -> None:
    catalog = load_catalog()
    rate_limits = RateLimitRegistry(kb=None)
    seller = SellerClient("c", "k", rate_limits=rate_limits)
    mcp = FastMCP("test")
    execution.register(mcp, catalog, seller, None)

    httpx_mock.add_response(
        url="https://api-seller.ozon.ru/v3/finance/transaction/list",
        method="POST",
        json={
            "result": {
                "operations": [{"operation_id": 42}],
                "page_count": 1,
                "row_count": 1,
            }
        },
        status_code=200,
    )

    result = _parse(
        await mcp.call_tool(
            "ozon_call_method",
            {
                "operation_id": "FinanceAPI_FinanceTransactionListV3",
                "params": {
                    "filter": {
                        "date": {
                            "from": "2026-01-01T00:00:00Z",
                            "to": "2026-01-31T23:59:59Z",
                        }
                    },
                    "page": 1,
                    "page_size": 100,
                },
            },
        )
    )
    assert result["ok"] is True
    assert result["response"]["result"]["row_count"] == 1
    await seller.aclose()
