#!/usr/bin/env python3
"""Auto-generate subscription_overrides.yaml entries from Ozon swagger text.

Walks both bundled swagger specs, scans every operation's summary,
description and x-* extensions for subscription tier mentions, and
emits a YAML list that can be merged into the main
`src/ozon_mcp/knowledge/subscription_overrides.yaml`.

Curated entries (source != "swagger") are preserved verbatim during
the merge — this script is safe to re-run after manual edits.

Usage
-----
    python scripts/generate_subscription_overrides.py [--apply]

Without `--apply` it writes two artefacts next to the YAML:
    subscription_overrides_auto.yaml   — machine-generated list
    subscription_overrides_report.txt  — stats

With `--apply` it additionally merges the generated entries into the
main overrides file (sorted by operation_id, curated entries untouched).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SELLER_SPEC = REPO_ROOT / "src" / "ozon_mcp" / "data" / "seller_swagger.json"
PERF_SPEC = REPO_ROOT / "src" / "ozon_mcp" / "data" / "perf_swagger.json"
KNOWLEDGE_DIR = REPO_ROOT / "src" / "ozon_mcp" / "knowledge"
MAIN_YAML = KNOWLEDGE_DIR / "subscription_overrides.yaml"
AUTO_YAML = KNOWLEDGE_DIR / "subscription_overrides_auto.yaml"
REPORT_TXT = KNOWLEDGE_DIR / "subscription_overrides_report.txt"


# Detection patterns — ordered strictest → broadest. First match wins
# so that "Premium Pro" beats "Premium", and "Premium Plus" beats plain
# "Premium". Case-insensitive, tolerant to hyphen/underscore/space.
TIER_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "PREMIUM_PRO": [
        re.compile(r"premium[\s\-_]*pro\b", re.IGNORECASE),
        re.compile(r"премиум\s*про", re.IGNORECASE),
    ],
    "PREMIUM_PLUS": [
        re.compile(r"premium[\s\-_]*plus\b", re.IGNORECASE),
        re.compile(r"премиум\s*плюс", re.IGNORECASE),
    ],
    "PREMIUM": [
        # Bare "Premium" must not be followed by Pro or Plus.
        re.compile(r"\bpremium\b(?![\s\-_]*(?:pro|plus))", re.IGNORECASE),
        re.compile(r"\bпремиум\b(?![\s\-_]*(?:про|плюс))", re.IGNORECASE),
    ],
}

# Fields we scan for tier mentions.
TEXT_FIELDS = ("summary", "description")


def _collect_operation_text(op: dict[str, Any]) -> str:
    parts: list[str] = []
    for f in TEXT_FIELDS:
        v = op.get(f)
        if isinstance(v, str):
            parts.append(v)
    # Also walk any x-* extension values (stringified — deep enough for keywords).
    for k, v in op.items():
        if not k.startswith("x-"):
            continue
        try:
            parts.append(json.dumps(v, ensure_ascii=False))
        except Exception:
            parts.append(str(v))
    tags = op.get("tags")
    if isinstance(tags, list):
        parts.append(" ".join(str(t) for t in tags))
    return "\n".join(parts)


_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
# URL-looking fragments. Three flavours that actually show up in Ozon
# swagger: full `https://…`, scheme-less `//host/…` (appears when the
# 80-char left window landed inside a URL), and bare `host/path)` tails.
_FULL_URL_RE = re.compile(r"https?://\S+")
_SCHEMELESS_URL_RE = re.compile(r"//\S+")
_HOST_PATH_TAIL_RE = re.compile(r"[\w.-]+\.(?:ru|com|org)/\S*")


def _clean_note(text: str, max_chars: int = 160) -> str:
    """Strip markdown links / bare URLs, collapse whitespace, truncate cleanly.

    The raw swagger text around a `Premium*` hit is usually a sentence full
    of markdown references to seller-edu.ozon.ru — a sliced substring of
    that is what used to land in the note field and read like garbage
    (`rating/subscription-premium-plus) или [Premium Pro](…`). This helper
    produces a human-readable note instead.
    """
    if not text:
        return ""
    # Replace full markdown links with their visible text.
    text = _MD_LINK_RE.sub(r"\1", text)
    # Drop whole URLs, then their scheme-less / host-path fragments that
    # survive when the snippet started mid-URL.
    text = _FULL_URL_RE.sub("", text)
    text = _SCHEMELESS_URL_RE.sub("", text)
    text = _HOST_PATH_TAIL_RE.sub("", text)
    # Strip simple HTML (swagger uses `<br>` / `<b>…</b>` inside descriptions).
    text = re.sub(r"<[^>]+>", " ", text)
    # Drop stray closing brackets / parens left over by half-cut markdown.
    text = re.sub(r"^[)\]\s,;.—-]+", "", text)
    text = re.sub(r"[(\[]+$", "", text)
    # Collapse any whitespace (including newlines) into single spaces.
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    # Truncate on a word boundary where possible.
    truncated = text[:max_chars].rstrip()
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.6:
        truncated = truncated[:last_space]
    return truncated.rstrip(" ,;:—-") + "…"


def _classify(text: str) -> tuple[str | None, str | None]:
    """Return (tier, matched_snippet) or (None, None) if no mention."""
    for tier, patterns in TIER_PATTERNS.items():
        for p in patterns:
            m = p.search(text)
            if m:
                start = max(0, m.start() - 80)
                end = min(len(text), m.end() + 160)
                snippet = text[start:end]
                return tier, _clean_note(snippet)
    return None, None


def _iter_operations(spec: dict[str, Any]) -> Iterable[tuple[str, str, dict[str, Any]]]:
    for path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for http_method, op in methods.items():
            if not isinstance(op, dict):
                continue
            if http_method.lower() not in (
                "get", "post", "put", "patch", "delete"
            ):
                continue
            yield path, http_method.upper(), op


def scan_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of auto-classified entries for one spec."""
    out: list[dict[str, Any]] = []
    for path, http_method, op in _iter_operations(spec):
        op_id = op.get("operationId") or f"{http_method} {path}"
        text = _collect_operation_text(op)
        if not text.strip():
            continue
        tier, snippet = _classify(text)
        if tier is None:
            continue
        out.append(
            {
                "operation_id": op_id,
                "endpoint": path,
                "required_tier": tier,
                "source": "swagger",
                "note": (
                    snippet or f"Auto-matched {tier} mention in swagger."
                ),
            }
        )
    return out


def load_curated(yaml_path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    """Read the existing overrides file; return (curated_entries, auto_op_ids).

    Curated entries = records whose ``source`` is not ``swagger``
    (everything a human has touched or that embeds empirical data).
    ``auto_op_ids`` is the set of operation_ids that came from a previous
    auto-generation run; those get overwritten each time.
    """
    if not yaml_path.exists():
        return [], set()
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or []
    curated: list[dict[str, Any]] = []
    auto_op_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        op_id = item.get("operation_id")
        if not op_id:
            continue
        source = (item.get("source") or "").lower()
        if source == "swagger":
            auto_op_ids.add(op_id)
        else:
            curated.append(item)
    return curated, auto_op_ids


def merge(
    curated: list[dict[str, Any]],
    auto: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    curated_ops = {c["operation_id"] for c in curated}
    # Drop auto entries that clash with curated ones.
    merged = list(curated)
    for entry in auto:
        if entry["operation_id"] in curated_ops:
            continue
        merged.append(entry)
    merged.sort(key=lambda e: (e["operation_id"], e.get("endpoint") or ""))
    return merged


# Custom YAML dumper so multi-line notes survive as block-literals.
class _YamlDumper(yaml.SafeDumper):
    pass


def _str_representer(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_YamlDumper.add_representer(str, _str_representer)


YAML_HEADER = """\
# Curated subscription requirements per operation_id.
#
# `required_tier` possible values:
#   PREMIUM, PREMIUM_PLUS, PREMIUM_PRO — hard gate (403 without this tier)
#   "unknown"  — we haven't verified
#   null       — method works on every tariff (no subscription required)
#
# `source` tracks provenance:
#   swagger             — auto-detected from Ozon swagger description text
#   empirical           — confirmed by real 403 response from a lower-tier account
#   swagger+empirical   — swagger text + production log evidence match
#   curated             — decided by maintainer reading related Ozon docs
#   unknown             — best guess only
#
# Entries with source=swagger are auto-generated by
# scripts/generate_subscription_overrides.py. Edit other rows freely —
# the generator will not overwrite them.
"""


def dump_yaml(entries: list[dict[str, Any]], path: Path) -> None:
    path.write_text(
        YAML_HEADER
        + "\n"
        + yaml.dump(
            entries,
            Dumper=_YamlDumper,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )


def make_report(
    auto: list[dict[str, Any]],
    total_scanned: int,
    curated_count: int,
    merged_total: int,
) -> str:
    counts = Counter(e["required_tier"] for e in auto)
    lines: list[str] = []
    lines.append(f"Total operations scanned  : {total_scanned}")
    lines.append(f"Auto matches (source=swagger):")
    lines.append(f"  PREMIUM_PRO  : {counts.get('PREMIUM_PRO', 0)}")
    lines.append(f"  PREMIUM_PLUS : {counts.get('PREMIUM_PLUS', 0)}")
    lines.append(f"  PREMIUM      : {counts.get('PREMIUM', 0)}")
    lines.append(
        f"No subscription mention   : "
        f"{total_scanned - sum(counts.values())}"
    )
    lines.append("")
    lines.append(f"Curated entries kept      : {curated_count}")
    lines.append(f"Final merged file size    : {merged_total}")
    lines.append("")
    for tier in ("PREMIUM_PRO", "PREMIUM_PLUS", "PREMIUM"):
        hits = [e for e in auto if e["required_tier"] == tier]
        if not hits:
            continue
        lines.append(f"--- {tier} ({len(hits)}) ---")
        for h in hits[:50]:
            lines.append(f"  {h['operation_id']:<55} {h['endpoint']}")
        if len(hits) > 50:
            lines.append(f"  ... and {len(hits) - 50} more")
        lines.append("")
    return "\n".join(lines)


def run(
    seller_path: Path = SELLER_SPEC,
    perf_path: Path = PERF_SPEC,
    main_yaml: Path = MAIN_YAML,
    auto_yaml: Path = AUTO_YAML,
    report_txt: Path = REPORT_TXT,
    apply: bool = False,
) -> dict[str, Any]:
    """Run the generator. Returns a summary dict for programmatic use."""
    seller = json.loads(seller_path.read_text(encoding="utf-8"))
    perf = json.loads(perf_path.read_text(encoding="utf-8")) if perf_path.exists() else {"paths": {}}

    total_ops = sum(
        1 for _ in _iter_operations(seller)
    ) + sum(1 for _ in _iter_operations(perf))

    auto = scan_spec(seller) + scan_spec(perf)

    # Drop dupes (same op_id from two specs — can't actually happen but defensive).
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for entry in auto:
        if entry["operation_id"] in seen:
            continue
        seen.add(entry["operation_id"])
        deduped.append(entry)
    auto = deduped

    curated, _prior_auto = load_curated(main_yaml)
    merged = merge(curated, auto)

    dump_yaml(auto, auto_yaml)
    report = make_report(
        auto,
        total_scanned=total_ops,
        curated_count=len(curated),
        merged_total=len(merged),
    )
    report_txt.write_text(report, encoding="utf-8")

    if apply:
        dump_yaml(merged, main_yaml)

    return {
        "total_scanned": total_ops,
        "auto_matches": len(auto),
        "curated_kept": len(curated),
        "merged_total": len(merged),
        "auto_yaml": str(auto_yaml),
        "report_txt": str(report_txt),
        "main_yaml_updated": apply,
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Merge auto-generated entries into the main overrides YAML "
        "(curated rows remain untouched).",
    )
    args = parser.parse_args()
    summary = run(apply=args.apply)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
