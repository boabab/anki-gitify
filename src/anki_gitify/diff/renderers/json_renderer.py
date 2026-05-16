"""Serialize a `DiffEnvelope` to JSON.

The pydantic model already pins the shape; this is just a thin wrapper that
controls indentation and ensures `null` is emitted for the maximal-keys delta
shape (no `exclude_none`).
"""

from __future__ import annotations

import json

from ..model import DiffEnvelope


def render(envelope: DiffEnvelope, *, compact: bool = False) -> str:
    data = envelope.model_dump(mode="json")
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
