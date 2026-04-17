"""Typed exceptions for Ozon API interactions."""

from __future__ import annotations

from typing import Any


class OzonError(Exception):
    """Base class for all Ozon-related errors raised by ozon-mcp."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        operation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.operation_id = operation_id
        self.payload = payload or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "status_code": self.status_code,
            "operation_id": self.operation_id,
            "payload": self.payload,
        }


class OzonAuthError(OzonError):
    """Missing or invalid credentials (HTTP 401)."""


class OzonForbiddenError(OzonError):
    """Insufficient permissions or subscription tier (HTTP 403)."""


class OzonValidationError(OzonError):
    """Request payload failed Ozon-side validation (HTTP 400)."""


class OzonNotFoundError(OzonError):
    """Requested resource does not exist (HTTP 404)."""


class OzonConflictError(OzonError):
    """Request conflicts with current state (HTTP 409)."""


class OzonRateLimitError(OzonError):
    """Rate limit exceeded (HTTP 429)."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class OzonServerError(OzonError):
    """Ozon backend failure (HTTP 5xx)."""


class OzonClientValidationError(OzonError):
    """Request failed local jsonschema validation before being sent."""
