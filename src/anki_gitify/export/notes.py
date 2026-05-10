"""Serialize notes to per-notetype CSV files (one row per note)."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from .cards import NotePlacement
from .notetypes import NoteTypeRef


def emit_notes(
    col,
    note_ids: list[int],
    placements: dict[int, NotePlacement],
    slug_by_mid: dict[int, str],
    ref_by_mid: dict[int, NoteTypeRef],
    out_dir: Path,
) -> int:
    """Write `notes/<slug>.csv` per notetype. Returns count of notes written."""
    notes_dir = out_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    by_mid: dict[int, list[int]] = defaultdict(list)
    for nid in note_ids:
        note = col.get_note(nid)
        by_mid[note.mid].append(nid)

    written = 0
    for mid, nids in by_mid.items():
        ref = ref_by_mid[mid]
        slug = slug_by_mid[mid]
        path = notes_dir / f"{slug}.csv"

        # Build rows first so we can sort deterministically.
        rows: list[list[str]] = []
        for nid in nids:
            note = col.get_note(nid)
            placement = placements[nid]
            row = [
                note.guid,
                placement.home_path,
                " ".join(note.tags),
            ]
            row.extend(note.fields)
            rows.append(row)
        rows.sort(key=lambda r: (r[1], r[0]))  # (deck_path, guid)

        with path.open("w", encoding="utf-8", newline="\n") as fh:
            writer = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\n")
            header = ["guid", "deck_path", "tags"] + ref.fields
            writer.writerow(header)
            for row in rows:
                writer.writerow(row)
        written += len(rows)
    return written


def emit_cards_csv(
    placements: dict[int, NotePlacement],
    nid_to_guid: dict[int, str],
    out_dir: Path,
) -> int:
    """Write `cards.csv` with only the diverging ord rows. Returns row count."""
    overrides: list[tuple[str, int, str]] = []
    for nid, placement in placements.items():
        if not placement.overrides:
            continue
        guid = nid_to_guid[nid]
        for ord_idx, deck_path in placement.overrides:
            overrides.append((guid, ord_idx, deck_path))

    if not overrides:
        return 0
    overrides.sort(key=lambda r: (r[0], r[1]))

    path = out_dir / "cards.csv"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(["note_guid", "ord", "deck_path"])
        for row in overrides:
            writer.writerow([row[0], str(row[1]), row[2]])
    return len(overrides)
