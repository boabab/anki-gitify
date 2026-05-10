"""Test fixtures: build tiny synthetic .anki2 collections for round-tripping."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
from anki.collection import Collection

from anki_gitify.profile import ProfilePaths


@dataclass
class FixtureCollection:
    profile: ProfilePaths
    root_deck: str  # full deck path used as the export root


def _make_basic_models(col: Collection) -> tuple[int, int]:
    """Create a Bidirectional (2 templates) and a Cloze notetype.

    Returns (bidirectional_mid, cloze_mid).
    """
    # Bidirectional notetype
    m = col.models.new("Bidirectional")
    f1 = col.models.new_field("Front")
    col.models.add_field(m, f1)
    f2 = col.models.new_field("Back")
    col.models.add_field(m, f2)
    t1 = col.models.new_template("Front->Back")
    t1["qfmt"] = "{{Front}}"
    t1["afmt"] = "{{FrontSide}}<hr id=answer>{{Back}}"
    col.models.add_template(m, t1)
    t2 = col.models.new_template("Back->Front")
    t2["qfmt"] = "{{Back}}"
    t2["afmt"] = "{{FrontSide}}<hr id=answer>{{Front}}"
    col.models.add_template(m, t2)
    m["css"] = ".card { font-family: arial; font-size: 20px; text-align: center; color: black; background-color: white; }"
    col.models.add(m)
    bidir_mid = m["id"]

    # Cloze notetype
    c = col.models.new("Cloze1")
    c["type"] = 1  # CLOZE
    c_text = col.models.new_field("Text")
    col.models.add_field(c, c_text)
    c_extra = col.models.new_field("Extra")
    col.models.add_field(c, c_extra)
    ct = col.models.new_template("Cloze")
    ct["qfmt"] = "{{cloze:Text}}"
    ct["afmt"] = "{{cloze:Text}}<br>{{Extra}}"
    col.models.add_template(c, ct)
    c["css"] = ".card.cloze { color: blue; }"
    col.models.add(c)
    cloze_mid = c["id"]

    return bidir_mid, cloze_mid


def _add_note(col: Collection, mid: int, deck_id: int, fields: list[str], tags: list[str]) -> int:
    model = col.models.get(mid)
    note = col.new_note(model)
    for i, val in enumerate(fields):
        note.fields[i] = val
    note.tags = list(tags)
    col.add_note(note, deck_id)
    return note.id


def _build_basic(tmp_path: Path) -> FixtureCollection:
    profile_dir = tmp_path / "Anki2" / "User1"
    profile_dir.mkdir(parents=True, exist_ok=True)
    media_dir = profile_dir / "collection.media"
    media_dir.mkdir(exist_ok=True)
    col_path = profile_dir / "collection.anki2"

    col = Collection(str(col_path))
    try:
        bidir_mid, cloze_mid = _make_basic_models(col)

        # Decks: Top::Sub::Leaf, plus a sibling Top::Other
        col.decks.id("Top")
        sub_id = col.decks.id("Top::Sub")
        leaf_id = col.decks.id("Top::Sub::Leaf")
        other_id = col.decks.id("Top::Other")

        # Notes: 3 bidirectional notes (split across Sub and Leaf to exercise
        # the cross-deck shared-notetype path), 3 cloze notes (in Other).
        # Some fields contain HTML and image refs.
        _add_note(
            col,
            bidir_mid,
            sub_id,
            ["日 <img src=\"sun.png\">", "sun, day"],
            ["kanji", "n5"],
        )
        _add_note(
            col,
            bidir_mid,
            sub_id,
            ["月", "moon"],
            ["kanji"],
        )
        _add_note(
            col,
            bidir_mid,
            leaf_id,
            ["これは日本語です", "This is Japanese"],
            ["sentence"],
        )

        _add_note(
            col,
            cloze_mid,
            other_id,
            ["The capital of {{c1::France}} is {{c2::Paris}}.", "Geography fact"],
            ["geo"],
        )
        _add_note(
            col,
            cloze_mid,
            other_id,
            ["{{c1::Hydrogen}} has atomic number 1.", "Chem"],
            ["chem"],
        )
        _add_note(
            col,
            cloze_mid,
            other_id,
            ["[sound:hello.mp3] {{c1::greeting}}", ""],
            ["audio"],
        )

        # Fake media files
        (media_dir / "sun.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-image-bytes")
        (media_dir / "hello.mp3").write_bytes(b"ID3fake-audio-bytes")
        # Unreferenced extra file (should NOT be exported)
        (media_dir / "unused.txt").write_text("unused")

    finally:
        col.close()

    return FixtureCollection(
        profile=ProfilePaths(
            base=tmp_path / "Anki2",
            profile="User1",
            collection=col_path,
            media_dir=media_dir,
        ),
        root_deck="Top",
    )


def _build_with_filtered(tmp_path: Path) -> FixtureCollection:
    fix = _build_basic(tmp_path)

    col = Collection(str(fix.profile.collection))
    try:
        # Filtered deck under Top
        did1 = col.decks.new_filtered("Top::Cram::Recent")
        d1 = col.decks.get(did1)
        d1["terms"] = [["deck:Top::Sub", 100, 0]]
        d1["resched"] = True
        col.decks.save(d1)

        did2 = col.decks.new_filtered("Top::Cram::All")
        d2 = col.decks.get(did2)
        d2["terms"] = [["deck:Top::Other", 50, 5]]
        d2["resched"] = False
        col.decks.save(d2)
    finally:
        col.close()
    return fix


@pytest.fixture
def fixture_basic(tmp_path: Path) -> FixtureCollection:
    return _build_basic(tmp_path)


@pytest.fixture
def fixture_with_filtered(tmp_path: Path) -> FixtureCollection:
    return _build_with_filtered(tmp_path)


@pytest.fixture
def reimport_collection(tmp_path: Path):
    """Yield a callable that opens a fresh temp Collection and imports a .apkg.

    Returns a `(collection_path, media_dir)` ProfilePaths-like tuple via
    AnkiPackageImporter so we can re-export it.
    """
    counter = [0]

    def _do(apkg_path: Path) -> ProfilePaths:
        counter[0] += 1
        target_dir = tmp_path / f"reimport-{counter[0]}" / "User1"
        target_dir.mkdir(parents=True, exist_ok=True)
        media_dir = target_dir / "collection.media"
        media_dir.mkdir(exist_ok=True)
        col_path = target_dir / "collection.anki2"
        col = Collection(str(col_path))
        try:
            # Modern API in anki>=2.1.50: `col.import_anki_package`
            from anki.import_export_pb2 import (
                ImportAnkiPackageOptions,
                ImportAnkiPackageRequest,
                ImportAnkiPackageUpdateCondition,
            )
            req = ImportAnkiPackageRequest(
                package_path=str(apkg_path),
                options=ImportAnkiPackageOptions(
                    merge_notetypes=True,
                    update_notes=ImportAnkiPackageUpdateCondition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
                    update_notetypes=ImportAnkiPackageUpdateCondition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
                    with_scheduling=False,
                    with_deck_configs=False,
                ),
            )
            col.import_anki_package(req)
            col.save()
        finally:
            col.close()
        return ProfilePaths(
            base=target_dir.parent.parent,
            profile="User1",
            collection=col_path,
            media_dir=media_dir,
        )

    return _do
