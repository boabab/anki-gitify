"""Filtered-deck-specific tests: structure, determinism, .md regen."""

from __future__ import annotations

from pathlib import Path

import yaml

from anki_gitify.export.exporter import export
from anki_gitify.export.filtered import render_filtered_md


def test_filtered_decks_yaml_structure(tmp_path: Path, fixture_with_filtered) -> None:
    out_dir = tmp_path / "out"
    report = export(
        deck_name="Top",
        out_dir=out_dir,
        profile=fixture_with_filtered.profile,
    )

    assert report.filtered_decks == 2
    fd = yaml.safe_load((out_dir / "filtered_decks.yml").read_text())
    assert fd["schema_version"] == 1
    assert len(fd["filtered_decks"]) == 2

    # Sorted alphabetically by name
    names = [e["name"] for e in fd["filtered_decks"]]
    assert names == ["Top::Cram::All", "Top::Cram::Recent"]

    cram_recent = next(e for e in fd["filtered_decks"] if e["name"] == "Top::Cram::Recent")
    assert cram_recent["resched"] is True
    assert cram_recent["terms"] == [
        {"search": "deck:Top::Sub", "limit": 100, "order": 0}
    ]

    cram_all = next(e for e in fd["filtered_decks"] if e["name"] == "Top::Cram::All")
    assert cram_all["resched"] is False
    assert cram_all["terms"] == [
        {"search": "deck:Top::Other", "limit": 50, "order": 5}
    ]

    # FILTERED_DECKS.md exists and matches what render_filtered_md would generate
    md_actual = (out_dir / "FILTERED_DECKS.md").read_text()
    md_expected = render_filtered_md(fd["filtered_decks"])
    assert md_actual == md_expected
    # And it actually contains both deck names somewhere
    assert "Top::Cram::Recent" in md_actual
    assert "Top::Cram::All" in md_actual


def test_filtered_export_is_deterministic(tmp_path: Path, fixture_with_filtered) -> None:
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    export(deck_name="Top", out_dir=out1, profile=fixture_with_filtered.profile)
    export(deck_name="Top", out_dir=out2, profile=fixture_with_filtered.profile)

    yml1 = (out1 / "filtered_decks.yml").read_bytes()
    yml2 = (out2 / "filtered_decks.yml").read_bytes()
    assert yml1 == yml2

    md1 = (out1 / "FILTERED_DECKS.md").read_bytes()
    md2 = (out2 / "FILTERED_DECKS.md").read_bytes()
    assert md1 == md2


def test_filtered_decks_excluded_from_deck_tree(tmp_path: Path, fixture_with_filtered) -> None:
    """Filtered decks themselves must not appear under decks/ — only normal decks do.

    Note: Anki auto-creates `Top::Cram` as a normal (empty) parent deck because the
    filtered decks under it use `::` hierarchy. That parent IS a real normal deck,
    so it correctly lands under decks/. What must NOT appear is `Recent` or `All`.
    """
    out_dir = tmp_path / "out"
    export(deck_name="Top", out_dir=out_dir, profile=fixture_with_filtered.profile)

    decks_dir = out_dir / "decks"
    forbidden = {"Recent", "All"}
    for path in decks_dir.rglob("deck.yml"):
        meta = yaml.safe_load(path.read_text())
        assert meta["name"] not in forbidden, f"filtered deck leaked into tree: {path}"
