"""Loads and indexes the YAML knowledge base."""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import yaml
from pydantic import TypeAdapter

from ozon_mcp.knowledge.models import (
    DeprecatedMethod,
    DescriptionOverride,
    ErrorEntry,
    MethodExample,
    PaginationPattern,
    Quirk,
    RateLimit,
    SafetyOverride,
    SubscriptionRequirement,
    Workflow,
)

WORKFLOWS_RESOURCE = "workflows.yaml"
RATE_LIMITS_RESOURCE = "rate_limits.yaml"
ERROR_CODES_RESOURCE = "error_codes.yaml"
QUIRKS_RESOURCE = "quirks.yaml"
EXAMPLES_RESOURCE = "examples.yaml"
SAFETY_OVERRIDES_RESOURCE = "safety_overrides.yaml"
SUBSCRIPTION_OVERRIDES_RESOURCE = "subscription_overrides.yaml"
DEPRECATED_METHODS_RESOURCE = "deprecated_methods.yaml"
PAGINATION_PATTERNS_RESOURCE = "pagination_patterns.yaml"
DESCRIPTIONS_OVERRIDES_RESOURCE = "descriptions_overrides.yaml"


def _load_yaml(resource: str) -> Any:
    pkg = files("ozon_mcp.knowledge")
    text = (pkg / resource).read_text(encoding="utf-8")
    return yaml.safe_load(text) or []


def _load_yaml_optional(resource: str) -> Any:
    """Like _load_yaml but tolerates missing files for forward compatibility."""
    pkg = files("ozon_mcp.knowledge")
    try:
        text = (pkg / resource).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    return yaml.safe_load(text) or []


class KnowledgeBase:
    def __init__(
        self,
        workflows: list[Workflow],
        rate_limits: list[RateLimit],
        errors: list[ErrorEntry],
        quirks: list[Quirk],
        examples: list[MethodExample],
        safety_overrides: list[SafetyOverride] | None = None,
        subscription_overrides: list[SubscriptionRequirement] | None = None,
        deprecated_methods: list[DeprecatedMethod] | None = None,
        pagination_patterns: list[PaginationPattern] | None = None,
        descriptions_overrides: list[DescriptionOverride] | None = None,
    ) -> None:
        self.workflows = workflows
        self.rate_limits = rate_limits
        self.errors = errors
        self.quirks = quirks
        self.examples = examples
        self.safety_overrides = safety_overrides or []
        self.subscription_overrides = subscription_overrides or []
        self.deprecated_methods = deprecated_methods or []
        self.pagination_patterns = pagination_patterns or []
        self._pagination_by_op: dict[str, PaginationPattern] = {
            p.operation_id: p for p in self.pagination_patterns
        }
        self.descriptions_overrides = descriptions_overrides or []
        self._descriptions_by_op: dict[str, DescriptionOverride] = {
            d.operation_id: d for d in self.descriptions_overrides
        }

        self._safety_overrides_by_op: dict[str, SafetyOverride] = {
            o.operation_id: o for o in self.safety_overrides
        }
        self._subscription_overrides_by_op: dict[str, SubscriptionRequirement] = {
            s.operation_id: s for s in self.subscription_overrides
        }
        self._deprecated_by_op: dict[str, DeprecatedMethod] = {
            d.operation_id: d for d in self.deprecated_methods
        }

        self._workflows_by_name: dict[str, Workflow] = {w.name: w for w in workflows}
        self._rate_limit_by_op: dict[str, RateLimit] = {
            r.operation_id: r for r in rate_limits if r.operation_id
        }
        self._rate_limit_by_section: dict[tuple[str | None, str], RateLimit] = {
            (r.api, r.section): r for r in rate_limits if r.section
        }
        self._quirks_by_op: dict[str, list[Quirk]] = {}
        for q in quirks:
            if q.operation_id:
                self._quirks_by_op.setdefault(q.operation_id, []).append(q)
        self._examples_by_op: dict[str, list[MethodExample]] = {}
        for e in examples:
            self._examples_by_op.setdefault(e.operation_id, []).append(e)
        self._errors_by_op: dict[str, list[ErrorEntry]] = {}
        for err in errors:
            if err.operation_id:
                self._errors_by_op.setdefault(err.operation_id, []).append(err)

    def get_workflow(self, name: str) -> Workflow | None:
        return self._workflows_by_name.get(name)

    def list_workflow_names(self) -> list[str]:
        return list(self._workflows_by_name.keys())

    def rate_limit_for(
        self, operation_id: str, api: str | None = None, section: str | None = None
    ) -> RateLimit | None:
        if operation_id in self._rate_limit_by_op:
            return self._rate_limit_by_op[operation_id]
        if section is not None:
            if (api, section) in self._rate_limit_by_section:
                return self._rate_limit_by_section[(api, section)]
            if (None, section) in self._rate_limit_by_section:
                return self._rate_limit_by_section[(None, section)]
        return None

    def quirks_for(self, operation_id: str) -> list[Quirk]:
        return list(self._quirks_by_op.get(operation_id, []))

    def examples_for(self, operation_id: str) -> list[MethodExample]:
        return list(self._examples_by_op.get(operation_id, []))

    def errors_for(self, operation_id: str) -> list[ErrorEntry]:
        return list(self._errors_by_op.get(operation_id, []))

    def errors_by_code(self, code: str) -> list[ErrorEntry]:
        return [e for e in self.errors if e.code == code]

    def safety_override_for(self, operation_id: str) -> SafetyOverride | None:
        return self._safety_overrides_by_op.get(operation_id)

    def subscription_for(self, operation_id: str) -> SubscriptionRequirement | None:
        return self._subscription_overrides_by_op.get(operation_id)

    def deprecated_for(self, operation_id: str) -> DeprecatedMethod | None:
        return self._deprecated_by_op.get(operation_id)

    def pagination_for(self, operation_id: str) -> PaginationPattern | None:
        return self._pagination_by_op.get(operation_id)

    def description_override_for(
        self, operation_id: str
    ) -> DescriptionOverride | None:
        return self._descriptions_by_op.get(operation_id)


_workflows_adapter = TypeAdapter(list[Workflow])
_rate_limits_adapter = TypeAdapter(list[RateLimit])
_errors_adapter = TypeAdapter(list[ErrorEntry])
_quirks_adapter = TypeAdapter(list[Quirk])
_examples_adapter = TypeAdapter(list[MethodExample])
_safety_overrides_adapter = TypeAdapter(list[SafetyOverride])
_subscription_overrides_adapter = TypeAdapter(list[SubscriptionRequirement])
_deprecated_methods_adapter = TypeAdapter(list[DeprecatedMethod])
_pagination_patterns_adapter = TypeAdapter(list[PaginationPattern])
_descriptions_overrides_adapter = TypeAdapter(list[DescriptionOverride])


def load_knowledge() -> KnowledgeBase:
    workflows = _workflows_adapter.validate_python(_load_yaml(WORKFLOWS_RESOURCE))
    rate_limits = _rate_limits_adapter.validate_python(_load_yaml(RATE_LIMITS_RESOURCE))
    errors = _errors_adapter.validate_python(_load_yaml(ERROR_CODES_RESOURCE))
    quirks = _quirks_adapter.validate_python(_load_yaml(QUIRKS_RESOURCE))
    examples = _examples_adapter.validate_python(_load_yaml(EXAMPLES_RESOURCE))
    safety_overrides = _safety_overrides_adapter.validate_python(
        _load_yaml(SAFETY_OVERRIDES_RESOURCE)
    )
    subscription_overrides = _subscription_overrides_adapter.validate_python(
        _load_yaml_optional(SUBSCRIPTION_OVERRIDES_RESOURCE)
    )
    deprecated_methods = _deprecated_methods_adapter.validate_python(
        _load_yaml_optional(DEPRECATED_METHODS_RESOURCE)
    )
    pagination_patterns = _pagination_patterns_adapter.validate_python(
        _load_yaml_optional(PAGINATION_PATTERNS_RESOURCE)
    )
    descriptions_overrides = _descriptions_overrides_adapter.validate_python(
        _load_yaml_optional(DESCRIPTIONS_OVERRIDES_RESOURCE)
    )
    return KnowledgeBase(
        workflows=workflows,
        rate_limits=rate_limits,
        errors=errors,
        quirks=quirks,
        examples=examples,
        safety_overrides=safety_overrides,
        subscription_overrides=subscription_overrides,
        deprecated_methods=deprecated_methods,
        pagination_patterns=pagination_patterns,
        descriptions_overrides=descriptions_overrides,
    )
