"""Test fixtures: anonymized Ozon API responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_RESPONSES_DIR = Path(__file__).parent / "responses"


def load_response(name: str) -> dict[str, Any]:
    """Load a fixture by short name (without ``_response.json`` suffix).

    Example: ``load_response("product_list")`` →
    ``tests/fixtures/responses/product_list_response.json``.
    """
    path = _RESPONSES_DIR / f"{name}_response.json"
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload
