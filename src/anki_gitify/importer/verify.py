"""Validate a gitified directory against the schema.

Read-only: never opens an Anki collection. Used by both `cli.py:verify_cmd`
and `anki_gitify.api.verify` so the CLI and the public API share one code
path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..export.filtered import render_filtered_md
from .loader import load


@dataclass
class VerifyReport:
    in_dir: Path
    ok: bool
    errors: list[str] = field(default_factory=list)
    notetypes: int = 0
    notes: int = 0
    media: int = 0
    filtered_decks: int = 0


def verify(in_dir: Path) -> VerifyReport:
    """Validate the gitified directory at ``in_dir``.

    Raises ``FileNotFoundError`` or ``ValueError`` if the directory cannot be
    loaded at all (e.g. missing ``gitify.yml``, unsupported schema version).
    For post-load structural issues (e.g. ``FILTERED_DECKS.md`` drift), the
    returned report has ``ok=False`` and the messages in ``errors``.
    """
    repo = load(Path(in_dir))

    errors: list[str] = []

    md_path = repo.in_dir / "FILTERED_DECKS.md"
    fd_dicts = [fd.model_dump() for fd in repo.filtered.filtered_decks]
    if fd_dicts:
        expected = render_filtered_md(fd_dicts)
        if not md_path.is_file():
            errors.append(
                f"{md_path} is missing but filtered_decks.yml has entries"
            )
        else:
            actual = md_path.read_text(encoding="utf-8")
            if actual != expected:
                errors.append(
                    f"{md_path} does not match what would be regenerated from filtered_decks.yml"
                )
    else:
        if md_path.is_file():
            errors.append(
                f"{md_path} exists but filtered_decks.yml is empty"
            )

    return VerifyReport(
        in_dir=Path(in_dir),
        ok=not errors,
        errors=errors,
        notetypes=len(repo.notetypes),
        notes=len(repo.notes),
        media=len(repo.media_files),
        filtered_decks=len(repo.filtered.filtered_decks),
    )
