"""Test the divergent-cards path: cards.csv emission + import error."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from anki.collection import Collection

from anki_gitify.export.exporter import export
from anki_gitify.importer.importer import CardOverrideError, import_ as run_import
from anki_gitify.profile import ProfilePaths


def _build_divergent(tmp_path: Path) -> ProfilePaths:
    """Build a fixture where one note's cards live in different decks."""
    profile_dir = tmp_path / "Anki2" / "User1"
    profile_dir.mkdir(parents=True, exist_ok=True)
    media_dir = profile_dir / "collection.media"
    media_dir.mkdir(exist_ok=True)
    col_path = profile_dir / "collection.anki2"

    col = Collection(str(col_path))
    try:
        # Bidirectional notetype (2 templates → 2 cards per note)
        m = col.models.new("Bidirectional")
        col.models.add_field(m, col.models.new_field("Front"))
        col.models.add_field(m, col.models.new_field("Back"))
        t1 = col.models.new_template("F->B")
        t1["qfmt"] = "{{Front}}"
        t1["afmt"] = "{{Back}}"
        col.models.add_template(m, t1)
        t2 = col.models.new_template("B->F")
        t2["qfmt"] = "{{Back}}"
        t2["afmt"] = "{{Front}}"
        col.models.add_template(m, t2)
        col.models.add(m)

        col.decks.id("Top")
        primary_did = col.decks.id("Top::Primary")
        secondary_did = col.decks.id("Top::Secondary")

        # Add a note with two cards
        note = col.new_note(col.models.get(m["id"]))
        note.fields = ["Hello", "World"]
        col.add_note(note, primary_did)

        # Move card ord=1 to Top::Secondary so the note's two cards land in
        # different decks.
        cards = note.cards()
        for c in cards:
            if c.ord == 1:
                c.did = secondary_did
                col.update_card(c)
    finally:
        col.close()

    return ProfilePaths(
        base=tmp_path / "Anki2",
        profile="User1",
        collection=col_path,
        media_dir=media_dir,
    )


def test_export_emits_cards_csv_for_divergent_note(tmp_path: Path) -> None:
    fix = _build_divergent(tmp_path)
    out = tmp_path / "out"
    report = export(deck_name="Top", out_dir=out, profile=fix)

    assert report.has_card_overrides
    cards_csv = out / "cards.csv"
    assert cards_csv.is_file()
    with cards_csv.open() as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    # header + exactly 1 override row (only the diverging ord)
    assert rows[0] == ["note_guid", "ord", "deck_path"]
    assert len(rows) == 2
    assert rows[1][1] == "1"
    assert rows[1][2] == "Top::Secondary"


def test_import_refuses_without_flag(tmp_path: Path) -> None:
    fix = _build_divergent(tmp_path)
    out = tmp_path / "out"
    export(deck_name="Top", out_dir=out, profile=fix)

    apkg = tmp_path / "out.apkg"
    with pytest.raises(CardOverrideError, match="cards.csv"):
        run_import(in_dir=out, out_apkg=apkg)


def test_import_proceeds_with_flag(tmp_path: Path) -> None:
    fix = _build_divergent(tmp_path)
    out = tmp_path / "out"
    export(deck_name="Top", out_dir=out, profile=fix)

    apkg = tmp_path / "out.apkg"
    report, _ = run_import(in_dir=out, out_apkg=apkg, ignore_card_overrides=True)
    assert apkg.is_file()
    assert report.card_overrides_ignored == 1
    assert report.notes == 1
