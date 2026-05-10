"""Top-level orchestrator: gitified directory → .apkg."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .genanki_build import build_package
from .loader import LoadedRepo, load


@dataclass
class ImportReport:
    out_apkg: Path
    notes: int
    media_files: int
    filtered_decks: int
    card_overrides_ignored: int


class CardOverrideError(RuntimeError):
    """Raised when cards.csv exists and --ignore-card-overrides was not passed."""


def import_(
    in_dir: Path,
    out_apkg: Path,
    *,
    ignore_card_overrides: bool = False,
) -> tuple[ImportReport, LoadedRepo]:
    in_dir = Path(in_dir)
    out_apkg = Path(out_apkg)

    repo = load(in_dir)

    if repo.card_overrides and not ignore_card_overrides:
        raise CardOverrideError(
            "cards.csv is present, which means at least one note has cards distributed "
            "across multiple decks. The v1 importer (genanki-based) cannot reproduce "
            "per-card deck placement and would silently lose this data. Pass "
            "--ignore-card-overrides to proceed (all cards of each affected note will "
            "land in the note's deck_path), or wait for v2's --lossless mode."
        )

    out_apkg.parent.mkdir(parents=True, exist_ok=True)
    build_package(repo, out_apkg)

    return (
        ImportReport(
            out_apkg=out_apkg,
            notes=len(repo.notes),
            media_files=len(repo.media_files),
            filtered_decks=len(repo.filtered.filtered_decks),
            card_overrides_ignored=len(repo.card_overrides),
        ),
        repo,
    )
