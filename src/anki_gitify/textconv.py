"""Humanize gitified files for line-based git diffs.

Used as a git `textconv` driver. Reads bytes from a single file (the form git
hands a textconv command) and returns a deterministic, diff-friendly text
rendering. Currently rewrites two file types:

  * `notes/<slug>.csv` — one wide row per note becomes a multi-line block per
    note keyed by `guid`, with tags one-per-line and each field as a labeled
    free-text section. A tag added by Anki shows up as one inserted line; a
    deck move as one edited line; a field edit as a normal text diff scoped
    to that field.

  * `cards.csv` — one line per override, sorted by (note_guid, ord).

Anything else is returned unchanged so the driver can be safely pointed at
broader path globs without surprising side effects.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

NOTES_HEADER_PREFIX = ("guid", "deck_path", "tags")
CARDS_HEADER = ("note_guid", "ord", "deck_path")

_NOTE_MARKER = "== note "
_FIELD_MARKER = "-- field: "


def humanize_path(path: Path) -> str:
    """Read `path` and return its humanized form (or original text if no rule applies)."""
    return humanize_bytes(path.read_bytes())


def humanize_bytes(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    rows = _try_parse_csv(text)
    if rows is None or not rows:
        return text
    header = tuple(rows[0])
    if len(header) >= 3 and header[:3] == NOTES_HEADER_PREFIX:
        return _render_notes(header, rows[1:])
    if header == CARDS_HEADER:
        return _render_cards(rows[1:])
    return text


def _try_parse_csv(text: str) -> list[list[str]] | None:
    try:
        return list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return None


def _render_notes(header: tuple[str, ...], rows: list[list[str]]) -> str:
    field_names = list(header[3:])
    notes: list[tuple[str, str, list[str], list[str]]] = []
    for row in rows:
        if not row:
            continue
        guid = row[0] if len(row) > 0 else ""
        deck = row[1] if len(row) > 1 else ""
        tags_raw = row[2] if len(row) > 2 else ""
        tags = sorted(tags_raw.split())
        fields = list(row[3 : 3 + len(field_names)])
        # pad short rows so field labels still line up
        while len(fields) < len(field_names):
            fields.append("")
        notes.append((guid, deck, tags, fields))
    notes.sort(key=lambda n: n[0])

    out: list[str] = []
    for guid, deck, tags, fields in notes:
        out.append(f"{_NOTE_MARKER}{guid} ==")
        out.append(f"deck: {deck}")
        if tags:
            out.append("tags:")
            for t in tags:
                out.append(f"  - {t}")
        else:
            out.append("tags: []")
        out.append("")
        for fname, fval in zip(field_names, fields):
            out.append(f"{_FIELD_MARKER}{fname} --")
            # preserve original whitespace verbatim; trailing newline
            # on the field is collapsed into our own block separator
            out.append(fval.rstrip("\n"))
            out.append("")
        out.append("")
    return "\n".join(out)


def _render_cards(rows: list[list[str]]) -> str:
    parsed: list[tuple[str, int, str]] = []
    for row in rows:
        if not row or len(row) < 3:
            continue
        try:
            ord_idx = int(row[1])
        except ValueError:
            continue
        parsed.append((row[0], ord_idx, row[2]))
    parsed.sort()
    if not parsed:
        return "# no card overrides\n"
    return "\n".join(
        f"override: note={guid}  ord={ord_idx}  deck={deck}"
        for guid, ord_idx, deck in parsed
    ) + "\n"
