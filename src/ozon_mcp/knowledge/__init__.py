"""Curated Ozon API knowledge — workflows, rate limits, errors, quirks, examples.

These YAML files complement the auto-extracted swagger schemas with information
that no machine can derive from OpenAPI alone: how methods chain together to
build a real data pipeline, which limits the docs hide, what surprises lurk in
specific endpoints. Loaded once at server start.
"""

from ozon_mcp.knowledge.loader import KnowledgeBase, load_knowledge
from ozon_mcp.knowledge.models import (
    DescriptionOverride,
    ErrorEntry,
    MethodExample,
    PaginationPattern,
    Quirk,
    RateLimit,
    SafetyOverride,
    Workflow,
    WorkflowStep,
)

__all__ = [
    "DescriptionOverride",
    "ErrorEntry",
    "KnowledgeBase",
    "MethodExample",
    "PaginationPattern",
    "Quirk",
    "RateLimit",
    "SafetyOverride",
    "Workflow",
    "WorkflowStep",
    "load_knowledge",
]
