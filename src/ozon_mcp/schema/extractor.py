"""Turns one OpenAPI operation into a Method with clean JSON Schema."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ozon_mcp.schema.resolver import RefResolver

AUTH_HEADERS = frozenset({"Client-Id", "Api-Key", "Authorization"})

# Tier ordering, lowest → highest. The auto-detected minimum tier is the
# lowest tier whose name appears in the method's text.
SUBSCRIPTION_TIERS: tuple[str, ...] = (
    "PREMIUM_LITE",
    "PREMIUM",
    "PREMIUM_PLUS",
    "PREMIUM_PRO",
)

# Patterns we look for in op + field descriptions. The order matters: more
# specific patterns must come BEFORE less specific ones so that "Premium Plus"
# is matched as PREMIUM_PLUS, not as plain PREMIUM.
_TIER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"premium[\s\-]*pro\b", re.IGNORECASE), "PREMIUM_PRO"),
    (re.compile(r"premium[\s\-]*plus\b", re.IGNORECASE), "PREMIUM_PLUS"),
    (re.compile(r"premium[\s\-]*lite\b", re.IGNORECASE), "PREMIUM_LITE"),
    (re.compile(r"premium\b", re.IGNORECASE), "PREMIUM"),
)


class Method(BaseModel):
    """One Ozon API endpoint with fully resolved schemas."""

    operation_id: str
    api: Literal["seller", "performance"]
    method: str
    path: str
    section: str
    tag: str
    summary: str
    description: str
    auth_type: str
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    request_schema: dict[str, Any] | None = None
    response_schemas: dict[str, dict[str, Any]] = Field(default_factory=dict)
    response_descriptions: dict[str, str] = Field(default_factory=dict)
    subscription_tiers_mentioned: list[str] = Field(default_factory=list)
    subscription_min_tier: str | None = None
    deprecated: bool = False
    deprecation_note: str | None = None
    safety: Literal["read", "write", "destructive"] = "write"
    safety_reason: str | None = None


class MethodExtractor:
    def __init__(self, resolver: RefResolver, api_label: Literal["seller", "performance"]) -> None:
        self.resolver = resolver
        self.api = api_label
        self.auth_type = (
            "Client-Id + Api-Key (headers)"
            if api_label == "seller"
            else "Authorization: Bearer {token}"
        )

    def extract(
        self,
        path: str,
        http_method: str,
        op: dict[str, Any],
        section: str,
        tag: str,
    ) -> Method:
        op = self.resolver.resolve(op)
        op = sanitize_schema(op)
        enrich_enums_from_description(op)

        parameters: list[dict[str, Any]] = []
        for p in op.get("parameters") or []:
            if not isinstance(p, dict):
                continue
            name = p.get("name", "")
            if not name or name in AUTH_HEADERS:
                continue
            parameters.append(
                {
                    "name": name,
                    "in": p.get("in", ""),
                    "required": bool(p.get("required", False)),
                    "description": _clean(p.get("description", "")),
                    "schema": p.get("schema", {}),
                }
            )

        request_schema: dict[str, Any] | None = None
        rb = op.get("requestBody")
        if isinstance(rb, dict):
            content = rb.get("content") or {}
            json_content = content.get("application/json") or {}
            schema = json_content.get("schema")
            if isinstance(schema, dict) and schema:
                request_schema = schema

        response_schemas: dict[str, dict[str, Any]] = {}
        response_descriptions: dict[str, str] = {}
        for code, resp in (op.get("responses") or {}).items():
            if not isinstance(resp, dict):
                continue
            response_descriptions[code] = _clean(resp.get("description", ""))
            content = resp.get("content") or {}
            json_content = content.get("application/json") or {}
            schema = json_content.get("schema")
            if isinstance(schema, dict) and schema:
                response_schemas[code] = schema

        tiers = _detect_subscription_tiers(op, request_schema, response_schemas)
        deprecated, deprecation_note = _detect_deprecated(op)
        safety, safety_reason = _classify_safety(http_method, path, op.get("operationId", ""))

        return Method(
            operation_id=op.get("operationId", ""),
            api=self.api,
            method=http_method.upper(),
            path=path,
            section=section,
            tag=tag,
            summary=(op.get("summary") or "").strip(),
            description=_clean(op.get("description", "")),
            auth_type=self.auth_type,
            parameters=parameters,
            request_schema=request_schema,
            response_schemas=response_schemas,
            response_descriptions=response_descriptions,
            subscription_tiers_mentioned=tiers,
            subscription_min_tier=_min_tier(tiers),
            deprecated=deprecated,
            deprecation_note=deprecation_note,
            safety=safety,  # type: ignore[arg-type]
            safety_reason=safety_reason,
        )


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# JSON Schema metadata keys whose value is supposed to be a non-null string or
# array. Ozon's swagger occasionally emits `null` for these (e.g.
# `enum: null` on enum-typed string fields), which produces invalid JSON Schema
# fragments and causes Draft 2020-12 validators to throw SchemaError. We strip
# these offending keys during extraction so the resulting schema is always
# safe to feed into jsonschema.validate.
_DROP_IF_NULL_KEYS = frozenset(
    {
        "description",
        "title",
        "format",
        "$comment",
        "$id",
        "$schema",
        "contentMediaType",
        "contentEncoding",
        "enum",
        "examples",
        "required",
        "items",
        "properties",
        "additionalProperties",
        "patternProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
    }
)


def _clean(text: str) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


_VALID_JSON_TYPES = frozenset(
    {"string", "integer", "number", "boolean", "object", "array", "null"}
)
# Coerce known Ozon-isms to canonical JSON Schema types where possible.
_TYPE_COERCIONS = {
    "int": "integer",
    "int32": "integer",
    "int64": "integer",
    "long": "integer",
    "float": "number",
    "double": "number",
    "bool": "boolean",
    "timestamp": "string",
    "date-time": "string",
    "date": "string",
}
# Standard JSON Schema "format" values per Draft 2020-12 + common OpenAPI
# extensions. Anything else is treated as documentation noise and dropped
# during sanitization (Ozon sometimes puts a phone-number regex here).
_VALID_FORMATS = frozenset(
    {
        "date-time", "time", "date", "duration",
        "email", "idn-email",
        "hostname", "idn-hostname",
        "ipv4", "ipv6",
        "uri", "uri-reference", "iri", "iri-reference", "uuid",
        "uri-template",
        "json-pointer", "relative-json-pointer",
        "regex",
        # OpenAPI-specific
        "int32", "int64", "float", "double", "byte", "binary", "password",
    }
)


# Backtick-wrapped enum values from Ozon descriptions, e.g.:
#     - `awaiting_packaging` — ожидает упаковки,
#     - `awaiting_deliver` — ожидает отгрузки,
# We extract any backtick token whose contents look like an enum constant
# (alphanumeric/underscore/dash, 2-50 chars, no spaces).
_ENUM_BACKTICK_RE = re.compile(r"`([A-Za-z][A-Za-z0-9_\-]{1,49})`")
_MIN_ENUM_VALUES = 3


def enrich_enums_from_description(schema: Any) -> Any:
    """Walk the schema and fill in missing enum lists from descriptions.

    Ozon's swagger has many string-typed fields where the enum values are
    documented as a markdown bullet list in the description text instead of
    as a proper JSON Schema ``enum``. Example: ``AnalyticsGetData.dimension``
    has an empty/null enum but its description lists ``- `day` — день, -
    `week` — неделя`` etc. Without enrichment the agent would have to read
    walls of text and guess values; after enrichment the agent sees a clean
    ``enum: ["day","week","month",...]`` constraint.

    The walker is conservative: it only fills enum on properties that
    (a) are typed string OR are array-of-string, (b) currently have no
    enum or an empty enum, and (c) have at least three backtick values in
    the description that look like enum constants.
    """
    if isinstance(schema, dict):
        for value in schema.values():
            if isinstance(value, dict):
                enrich_enums_from_description(value)
            elif isinstance(value, list):
                for item in value:
                    enrich_enums_from_description(item)

        # Now decide if THIS dict represents an enum-able property.
        if _is_enum_eligible(schema):
            extracted = _extract_enum_values(schema.get("description", ""))
            if extracted is not None:
                target = schema
                if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
                    target = schema["items"]
                if "enum" not in target or not target.get("enum"):
                    target["enum"] = extracted
                    target["x-enum-source"] = "description"
    elif isinstance(schema, list):
        for item in schema:
            enrich_enums_from_description(item)
    return schema


def _is_enum_eligible(schema: dict[str, Any]) -> bool:
    if not schema.get("description"):
        return False
    t = schema.get("type")
    if t == "string":
        existing = schema.get("enum")
        return not existing
    if t == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            return False
        if items.get("type") != "string":
            return False
        return not items.get("enum")
    return False


def _extract_enum_values(description: str) -> list[str] | None:
    if not description or "`" not in description:
        return None
    matches = _ENUM_BACKTICK_RE.findall(description)
    if len(matches) < _MIN_ENUM_VALUES:
        return None
    # Dedupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            out.append(m)
    if len(out) < _MIN_ENUM_VALUES:
        return None
    return out


def sanitize_schema(node: Any) -> Any:
    """Make Ozon's swagger fragments safe to feed to jsonschema validators.

    Ozon's source swagger has several recurring quirks that violate the
    JSON Schema 2020-12 metaschema and would otherwise cause SchemaError
    before any data validation happens. This walker fixes the common ones:

    1. Drops metadata keys whose value is None (e.g. ``description: null``,
       ``enum: null``).
    2. Coerces non-standard ``type`` values (``int`` → ``integer``,
       ``bool`` → ``boolean``, ``timestamp`` → ``string``). Drops the type
       entirely if it's an informal description like ``"array of strings"``.
    3. Drops ``required: true|false`` siblings of ``type`` — that's a
       swagger-2.0 carry-over; required is supposed to live at the parent
       object level as an array of property names.
    4. Drops ``format`` values that aren't on the JSON Schema standard list
       (Ozon sometimes puts a regex like ``+7(XXX)XXX-XX-XX`` here).

    The cleaning is conservative: we only touch keys that we recognise as
    JSON Schema metadata. Everything else passes through unchanged so the
    schema's semantic meaning is preserved.
    """
    if isinstance(node, dict):
        result: dict[str, Any] = {}
        for k, v in node.items():
            if v is None and k in _DROP_IF_NULL_KEYS:
                continue
            if k == "type":
                fixed = _fix_type(v)
                if fixed is not None:
                    result[k] = fixed
                continue
            if k == "required" and isinstance(v, bool):
                # Misplaced legacy swagger 2.0 "required: true" sibling.
                continue
            if k == "format" and isinstance(v, str) and v not in _VALID_FORMATS:
                # Non-standard format hint (Ozon sometimes puts a regex
                # placeholder here). Drop it.
                continue
            if k == "pattern" and isinstance(v, str):
                try:
                    re.compile(v)
                except re.error:
                    # Ozon's swagger has placeholder strings like
                    # "+7(XXX)XXX-XX-XX" sitting in the pattern field that
                    # are not valid regexes. Drop them.
                    continue
            result[k] = sanitize_schema(v)
        return result
    if isinstance(node, list):
        return [sanitize_schema(item) for item in node]
    return node


def _fix_type(value: Any) -> Any:
    if isinstance(value, list):
        cleaned = [_fix_type(v) for v in value if _fix_type(v) is not None]
        return cleaned or None
    if not isinstance(value, str):
        return None
    if value in _VALID_JSON_TYPES:
        return value
    coerced = _TYPE_COERCIONS.get(value)
    if coerced:
        return coerced
    # Informal description like "array of strings" → drop, can't recover.
    return None


def _detect_subscription_tiers(
    op: dict[str, Any],
    request_schema: dict[str, Any] | None,
    response_schemas: dict[str, dict[str, Any]],
) -> list[str]:
    """Find every Premium tier name mentioned anywhere in this operation.

    Walks the op description, every parameter description, and every field
    description inside request and response schemas. Returns the set of
    detected tiers in canonical order. Empty list means no subscription
    keywords were found anywhere.
    """
    found: set[str] = set()
    _scan_text_for_tiers(op.get("description", ""), found)
    _scan_text_for_tiers(op.get("summary", ""), found)
    for p in op.get("parameters") or []:
        if isinstance(p, dict):
            _scan_text_for_tiers(p.get("description", ""), found)
    if request_schema:
        _scan_node_for_tiers(request_schema, found)
    for resp in response_schemas.values():
        _scan_node_for_tiers(resp, found)
    return [t for t in SUBSCRIPTION_TIERS if t in found]


def _scan_node_for_tiers(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        desc = node.get("description")
        if isinstance(desc, str):
            _scan_text_for_tiers(desc, found)
        for v in node.values():
            _scan_node_for_tiers(v, found)
    elif isinstance(node, list):
        for item in node:
            _scan_node_for_tiers(item, found)


def _scan_text_for_tiers(text: str, found: set[str]) -> None:
    if not text or "premium" not in text.lower():
        return
    # Track which character ranges have already been claimed by a more specific
    # match, so plain "Premium" inside "Premium Plus" doesn't double-count.
    claimed: list[tuple[int, int]] = []
    for pattern, tier in _TIER_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(c_start <= start < c_end for c_start, c_end in claimed):
                continue
            found.add(tier)
            claimed.append((start, end))


def _min_tier(tiers: list[str]) -> str | None:
    """Return the lowest tier in the list per SUBSCRIPTION_TIERS ordering."""
    if not tiers:
        return None
    for t in SUBSCRIPTION_TIERS:
        if t in tiers:
            return t
    return None


_READ_VERBS = frozenset(
    {
        # Real read verbs (and read-implying nouns that are unambiguous).
        "list", "info", "get", "tree", "totals", "count",
        "details", "history", "search", "find", "view", "show",
        "describe", "summary", "export", "fetch", "lookup",
        "preview", "status", "available", "values", "sources",
        "calendar",
        # NB: "statistics", "stats", "report" are intentionally NOT here.
        # Performance API uses POST /api/client/statistics as SubmitRequest
        # which creates an async report. Treating "statistics" as read would
        # misclassify that endpoint and let an audit script fire it.
    }
)

_WRITE_VERBS = frozenset(
    {
        "create", "update", "change", "set", "add", "edit", "save",
        "import", "upload", "send", "notify", "sync", "refresh",
        "activate", "deactivate", "enable", "disable", "start", "stop",
        "move", "pack", "ship", "draft", "apply", "calculate",
        "schedule", "exemplar", "giveout", "reorder",
        "approve", "dispute", "answer", "file", "print",
        "migrate", "transfer", "take", "redirect", "copy", "clone",
        "push", "pull", "patch", "replace",
        "finish", "pay", "checkout", "feedback", "ack", "confirm",
        "submit", "process", "execute",
        "register", "unregister", "attach", "detach", "bind", "unbind",
        "compensate", "verify", "receive",
        "carrots", "bid", "bids",
        "discount", "discounts", "discounted",
        "split", "merge", "label", "labels",
        "request", "generate",
        "mark",
    }
)

_DESTRUCTIVE_VERBS = frozenset(
    {
        "delete", "remove", "cancel", "archive", "unarchive",
        "destroy", "purge", "reject", "decline", "withdraw",
    }
)


def _classify_safety(method_http: str, path: str, operation_id: str) -> tuple[str, str]:
    """Classify a method's safety: read | write | destructive.

    Strategy:
    1. Look at the LAST path segment first (most actions live there).
    2. Then scan the operation_id CamelCase tokens.
    3. Then HTTP method as fallback.
    4. Default to ``write`` for unknown POSTs — it's the safer mistake.

    A read method that is misclassified as write only gets blocked from
    the audit allowlist (annoying). A write method misclassified as read
    can be called accidentally (catastrophic). The classifier biases
    aggressively toward write/destructive when in doubt.
    """
    p = path.rstrip("/").lower()
    segments = [s for s in p.split("/") if s]
    last_segment = segments[-1] if segments else ""
    # Strip path-template braces
    if last_segment.startswith("{") and len(segments) >= 2:
        last_segment = segments[-2]

    last_tokens = set(re.split(r"[_\-]", last_segment))
    op_tokens = {w.lower() for w in re.findall(r"[A-Za-z][a-z0-9]+", operation_id)}

    # 1. Last path segment is the strongest signal.
    if last_tokens & _DESTRUCTIVE_VERBS:
        matched = sorted(last_tokens & _DESTRUCTIVE_VERBS)[0]
        return "destructive", f"path segment '{last_segment}' contains '{matched}'"
    if last_tokens & _WRITE_VERBS:
        matched = sorted(last_tokens & _WRITE_VERBS)[0]
        return "write", f"path segment '{last_segment}' contains '{matched}'"
    if last_tokens & _READ_VERBS:
        matched = sorted(last_tokens & _READ_VERBS)[0]
        return "read", f"path segment '{last_segment}' contains '{matched}'"

    # 2. Operation_id CamelCase tokens.
    if op_tokens & _DESTRUCTIVE_VERBS:
        matched = sorted(op_tokens & _DESTRUCTIVE_VERBS)[0]
        return "destructive", f"operationId contains '{matched}'"
    if op_tokens & _WRITE_VERBS:
        matched = sorted(op_tokens & _WRITE_VERBS)[0]
        return "write", f"operationId contains '{matched}'"
    if op_tokens & _READ_VERBS:
        matched = sorted(op_tokens & _READ_VERBS)[0]
        return "read", f"operationId contains '{matched}'"

    # 3. HTTP method fallback.
    http = method_http.upper()
    if http == "DELETE":
        return "destructive", "HTTP DELETE"
    if http in ("PUT", "PATCH"):
        return "write", f"HTTP {http}"
    if http in ("GET", "HEAD"):
        return "read", f"HTTP {http}"

    # 4. Unknown POST — default to write (safer mistake).
    return "write", "POST without read indicators (default-to-write)"


_DEPRECATION_KEYWORDS = (
    "устарел",  # past — "стал устаревшим"
    "устаревш",  # participle — "устаревший метод"
    "устарева",  # present — "устаревает", "устаревают"
    "deprecated",
    "obsolete",
    "не используйте",
    "больше не доступен",
    "будет отключ",  # "будет отключён"
    "no longer",
    "use instead",
    "переключитесь на",  # "переключитесь на /v2/..."
)


def _detect_deprecated(op: dict[str, Any]) -> tuple[bool, str | None]:
    """Detect deprecated methods.

    Ozon's swagger sometimes has explicit `deprecated: true` on operations,
    but more often the deprecation note is buried in the description text
    ("Этот метод устарел, используйте ..."). We check both.
    """
    if op.get("deprecated") is True:
        return True, "marked deprecated in OpenAPI spec"

    text_blob = " ".join(
        [
            op.get("description", "") or "",
            op.get("summary", "") or "",
        ]
    ).lower()
    for kw in _DEPRECATION_KEYWORDS:
        if kw in text_blob:
            # Try to extract a one-sentence note for the agent.
            sentences = re.split(r"[.!?\n]", op.get("description", "") or "")
            for s in sentences:
                if any(k in s.lower() for k in _DEPRECATION_KEYWORDS):
                    return True, _clean(s)[:200]
            return True, "marked deprecated in description"
    return False, None
