"""v2 `apply-filtered`: write filtered-deck definitions into a live collection.

Reads `filtered_decks.yml` from a gitified directory and creates the matching
filtered decks in the user's collection via the official `anki` API. Idempotent:
a filtered deck whose name already exists as a *filtered* deck is left alone.

This is the one documented exception to the "never write to a live collection"
rule (see CLAUDE.md hard rule #1) — only filtered-deck metadata is touched, no
notes/cards/scheduling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .._yaml import load_yaml
from ..collection_io import open_collection
from ..schema import FilteredDecksFile


@dataclass
class ApplyFilteredReport:
    collection: Path
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def total(self) -> int:
        return len(self.created) + len(self.skipped) + len(self.conflicts)


def _load_filtered_spec(in_dir: Path) -> FilteredDecksFile:
    path = in_dir / "filtered_decks.yml"
    if not path.is_file():
        raise FileNotFoundError(
            f"No filtered_decks.yml in {in_dir}. Nothing to apply."
        )
    data = load_yaml(path)
    spec = FilteredDecksFile.model_validate(data)
    if spec.schema_version != 1:
        raise ValueError(
            f"Unsupported filtered_decks.yml schema_version: {spec.schema_version}. "
            "This anki-gitify build only understands version 1."
        )
    return spec


def apply_filtered(
    in_dir: Path,
    collection_path: Path,
    *,
    dry_run: bool = False,
) -> ApplyFilteredReport:
    """Create filtered decks from `<in_dir>/filtered_decks.yml` in the live collection.

    - Filtered decks whose name already exists as a filtered deck are skipped (idempotent).
    - Names that collide with an existing *normal* deck are reported as conflicts and
      not applied; the user must resolve manually.
    - With ``dry_run=True``, no writes happen — the report describes what would change.
    """
    in_dir = Path(in_dir)
    collection_path = Path(collection_path)

    spec = _load_filtered_spec(in_dir)
    report = ApplyFilteredReport(collection=collection_path, dry_run=dry_run)

    if not spec.filtered_decks:
        return report

    with open_collection(collection_path) as col:
        for entry in spec.filtered_decks:
            existing = col.decks.id_for_name(entry.name)
            if existing is not None:
                deck = col.decks.get(existing)
                if int(deck.get("dyn", 0)) == 1:
                    report.skipped.append(entry.name)
                else:
                    report.conflicts.append(entry.name)
                continue

            if dry_run:
                report.created.append(entry.name)
                continue

            did = col.decks.new_filtered(entry.name)
            deck = col.decks.get(did)
            deck["terms"] = [[t.search, t.limit, t.order] for t in entry.terms]
            deck["resched"] = entry.resched
            deck["delays"] = entry.delays
            col.decks.save(deck)
            report.created.append(entry.name)

    return report
