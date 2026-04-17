"""Pydantic models for the curated knowledge layer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkflowStep(BaseModel):
    n: int
    operation_id: str
    purpose: str
    pagination: str | None = None
    batching: str | None = None
    concurrency: str | None = None
    join_on: str | None = None
    notes: str | None = None


class WorkflowDbSchema(BaseModel):
    table: str
    primary_key: list[str]
    indexes: list[list[str]] = Field(default_factory=list)
    engine_clickhouse: str | None = None
    engine_postgres: str | None = None


WorkflowCategory = Literal[
    "catalog",
    "orders",
    "analytics",
    "health",
    "pricing",
    "content",
    "advertising",
    "warehouse",
    "returns",
    "finance",
]


class Workflow(BaseModel):
    name: str
    title: str
    description: str
    category: WorkflowCategory | None = None
    recommended_schedule: str | None = None
    recommended_db_schema: WorkflowDbSchema | None = None
    steps: list[WorkflowStep]
    gotchas: list[str] = Field(default_factory=list)
    review_status: Literal["draft", "verified"] = "draft"
    rate_limit_note: str | None = None
    subscription_note: str | None = None
    interpret: str | None = None
    when_to_use: list[str] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)


class RateLimit(BaseModel):
    """Per-section or per-method rate limit.

    Either operation_id OR section must be set. operation_id wins on conflict.
    """

    operation_id: str | None = None
    section: str | None = None
    api: Literal["seller", "performance"] | None = None
    per_minute: int | None = None
    per_day: int | None = None
    burst: int | None = None
    note: str | None = None
    source: Literal["docs", "curated", "guess", "empirical"] = "guess"


class ErrorEntry(BaseModel):
    code: str
    http_status: int | None = None
    operation_id: str | None = None
    api: Literal["seller", "performance"] | None = None
    title: str
    cause: str
    fix: str
    related_methods: list[str] = Field(default_factory=list)


class Quirk(BaseModel):
    operation_id: str | None = None
    section: str | None = None
    api: Literal["seller", "performance"] | None = None
    title: str
    description: str
    severity: Literal["info", "warning", "critical"] = "info"
    extracted_from: Literal["description", "curated"] = "curated"
    business_context: str | None = None
    when_to_use: list[str] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    safety_warning: str | None = None


class MethodExample(BaseModel):
    operation_id: str
    title: str
    description: str | None = None
    request: dict[str, Any]
    response_excerpt: dict[str, Any] | None = None


class SafetyOverride(BaseModel):
    operation_id: str
    safety: Literal["read", "write", "destructive"]
    reason: str


class SubscriptionRequirement(BaseModel):
    """Curated access-tier requirement for an Ozon method.

    Auto-extraction from swagger text mentions tiers but doesn't tell whether
    the API returns a hard 403 or just a soft data-limit for sellers below
    the tier. This file records the actual requirement, with provenance.
    """

    operation_id: str
    required_tier: Literal["PREMIUM", "PREMIUM_PLUS", "PREMIUM_PRO", "unknown"] | None = None
    # None here means "no subscription required" — the method is available on
    # every tariff, verified empirically or by docs silence.
    source: Literal[
        "swagger",
        "empirical",
        "swagger+empirical",
        "swagger+curated",
        "curated",
        "unknown",
    ] = "unknown"
    note: str | None = None


class PaginationPattern(BaseModel):
    """How to walk all pages of a list endpoint.

    Filled by knowledge/pagination_patterns.yaml — auto-extracted from
    swagger and curated for shape (which field to advance, which response
    field carries the items array).
    """

    operation_id: str
    type: Literal["offset_limit", "page_number", "last_id", "cursor", "page_token"]
    request_offset_field: str | None = None
    request_limit_field: str = "limit"
    response_items_field: str = "items"
    response_total_field: str | None = None
    default_limit: int = 1000
    max_limit: int = 1000


class DescriptionOverride(BaseModel):
    """Curated replacement for an Ozon method's description.

    Used when Ozon shipped the method with empty description (only
    summary present) but it is hot-path enough to deserve real text for
    BM25 search and ozon_describe_method output.
    """

    operation_id: str
    description: str
    source: Literal["curated"] = "curated"


class DeprecatedMethod(BaseModel):
    """An operation_id we used to ship in the catalogue but Ozon has removed
    from their spec. Kept as a tombstone so existing clients get a clean
    'deprecated' signal rather than a 'method not found' error."""

    operation_id: str
    path: str | None = None
    http_method: str | None = None
    removed_on: str | None = None  # ISO date
    replacement: str | None = None  # operation_id of successor, if any
    note: str | None = None
