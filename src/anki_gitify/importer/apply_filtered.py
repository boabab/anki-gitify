"""Stub for v2: programmatically create filtered decks in a live collection.

The implementation sketch lives in the plan file; this module raises
NotImplementedError so the CLI can register the subcommand and surface a
helpful message until v2 ships.
"""

from __future__ import annotations

from pathlib import Path


def apply_filtered(in_dir: Path, collection_path: Path) -> int:  # pragma: no cover
    raise NotImplementedError(
        "apply-filtered is planned for v2 and not yet implemented. "
        "For now, recreate filtered decks manually via Tools → Create Filtered Deck "
        f"using the entries in {in_dir / 'filtered_decks.yml'}."
    )
