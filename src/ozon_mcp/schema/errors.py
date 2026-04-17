"""Unified pydantic model for all errors returned by Ozon MCP tools.

The model is intentionally permissive — every field after ``error_type`` /
``message`` is optional so call sites can populate only what they know. The
shape is the contract MCP clients depend on; do not rename existing fields.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ErrorType = Literal[
    "rate_limit",
    "subscription_gate",
    "invalid_params",
    "not_found",
    "server_error",
    "timeout",
    "auth",
    "forbidden",
    "conflict",
    "deprecated",
    "missing_credentials",
    "write_requires_confirmation",
    "destructive_requires_double_confirmation",
    "validation",
    "unknown",
]


class OzonError(BaseModel):
    """Structured error envelope returned by tools that talk to Ozon.

    Always carries ``error`` (legacy short tag) and ``error_type`` (canonical
    enum). Old clients keying off ``error == "subscription_gate"`` keep
    working while new ones can switch to ``error_type``.
    """

    model_config = ConfigDict(extra="allow")

    error: str
    error_type: ErrorType
    message: str
    code: int | str | None = None
    operation_id: str | None = None
    endpoint: str | None = None
    status_code: int | None = None
    retryable: bool = False
    retry_after_seconds: int | None = None
    required_tier: str | None = None
    cabinet_tier: str | None = None
    http_call_skipped: bool = False
    payload: dict[str, Any] | None = None
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


def make_error(
    error_type: ErrorType,
    message: str,
    **fields: Any,
) -> dict[str, Any]:
    """Convenience constructor — same envelope as execution.py uses.

    Lets the read-only knowledge tools return errors in the same shape as
    the execution layer without duplicating the boilerplate. Pop ``error``
    out of ``fields`` so callers can override the legacy short tag (e.g.
    ``error="NotFound"`` for backwards compat) without it shadowing
    ``error_type``.
    """
    return OzonError(
        error=fields.pop("error", error_type),
        error_type=error_type,
        message=message,
        **fields,
    ).to_dict()
