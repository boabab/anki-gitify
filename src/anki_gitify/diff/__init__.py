"""Semantic diff between two states of a gitified deck.

See [`docs/DESIGN.md`](../../../docs/DESIGN.md) §"Semantic diff" for the contract.
"""

from .differ import RevInput, run_diff
from .model import DIFF_SCHEMA_VERSION, DiffEnvelope


__all__ = [
    "DIFF_SCHEMA_VERSION",
    "DiffEnvelope",
    "RevInput",
    "run_diff",
]
