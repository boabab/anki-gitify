"""Smoke tests for the export side."""

from __future__ import annotations

import csv
from pathlib import Path

import yaml

from anki_gitify.export.exporter import export


def test_export_basic_layout(tmp_path: Path, fixture_basic) -> None:
    out_dir = tmp_path / "out"
    report = export(
        deck_name="Top",
        out_dir=out_dir,
        profile=fixture_basic.profile,
    )

    # Top-level files exist
    assert (out_dir / "gitify.yml").is_file()
    assert (out_dir / "deck.yml").is_file()
    assert (out_dir / "filtered_decks.yml").is_file()

    # filtered_decks.yml should be empty (no filtered decks in fixture_basic)
    fd = yaml.safe_load((out_dir / "filtered_decks.yml").read_text())
    assert fd == {"schema_version": 1, "filtered_decks": []}
    # No FILTERED_DECKS.md when there are no filtered decks
    assert not (out_dir / "FILTERED_DECKS.md").exists()

    # Deck tree
    sub_yml = out_dir / "decks" / "sub" / "deck.yml"
    leaf_yml = out_dir / "decks" / "sub" / "decks" / "leaf" / "deck.yml"
    other_yml = out_dir / "decks" / "other" / "deck.yml"
    for path in (sub_yml, leaf_yml, other_yml):
        assert path.is_file(), path

    # Notetypes (slugged)
    nt_dir = out_dir / "notetypes"
    assert (nt_dir / "bidirectional" / "meta.yml").is_file()
    assert (nt_dir / "bidirectional" / "fields.yml").is_file()
    assert (nt_dir / "bidirectional" / "style.css").is_file()
    assert (nt_dir / "bidirectional" / "templates" / "00-front-back").is_dir()
    assert (nt_dir / "bidirectional" / "templates" / "01-back-front").is_dir()
    assert (nt_dir / "cloze1" / "meta.yml").is_file()

    # Notes CSV per notetype
    bidir_csv = out_dir / "notes" / "bidirectional.csv"
    cloze_csv = out_dir / "notes" / "cloze1.csv"
    assert bidir_csv.is_file()
    assert cloze_csv.is_file()

    # CSV header includes deck_path
    with bidir_csv.open() as fh:
        header = next(csv.reader(fh))
    assert header == ["guid", "deck_path", "tags", "Front", "Back"]

    # Cross-deck shared notetype: bidirectional rows have multiple distinct deck_paths
    with bidir_csv.open() as fh:
        reader = csv.reader(fh)
        next(reader)
        deck_paths = {row[1] for row in reader}
    assert deck_paths == {"Top::Sub", "Top::Sub::Leaf"}

    # Counts in report
    assert report.notetypes == 2
    assert report.notes == 6
    assert report.cards >= 6  # at least one card per note (bidir gives 2)
    assert report.filtered_decks == 0
    assert not report.has_card_overrides

    # Media: only referenced files copied
    media_dir = out_dir / "media"
    media_files = sorted(p.name for p in media_dir.iterdir())
    assert media_files == ["hello.mp3", "sun.png"]


def test_export_force_required_to_overwrite(tmp_path: Path, fixture_basic) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "stale.txt").write_text("hi")

    import pytest

    with pytest.raises(FileExistsError):
        export(
            deck_name="Top",
            out_dir=out_dir,
            profile=fixture_basic.profile,
        )


def test_export_rejects_filtered_root(tmp_path: Path, fixture_with_filtered) -> None:
    out_dir = tmp_path / "out"
    import pytest

    with pytest.raises(ValueError, match="filtered deck"):
        export(
            deck_name="Top::Cram::Recent",
            out_dir=out_dir,
            profile=fixture_with_filtered.profile,
        )


def test_export_unknown_deck(tmp_path: Path, fixture_basic) -> None:
    import pytest

    with pytest.raises(ValueError, match="not found"):
        export(
            deck_name="Nonexistent",
            out_dir=tmp_path / "out",
            profile=fixture_basic.profile,
        )
