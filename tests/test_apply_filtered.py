"""Tests for the v2 `apply-filtered` subcommand: writes filtered-deck
definitions back into a live collection.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from anki.collection import Collection
from typer.testing import CliRunner

from anki_gitify.cli import app
from anki_gitify.export.exporter import export
from anki_gitify.importer.apply_filtered import apply_filtered


runner = CliRunner()


def _filtered_decks(col_path: Path) -> dict[str, dict]:
    """Return {name: deck_dict} for every filtered deck in the collection."""
    col = Collection(str(col_path))
    try:
        out: dict[str, dict] = {}
        for entry in col.decks.all_names_and_ids():
            deck = col.decks.get(entry.id)
            if int(deck.get("dyn", 0)) == 1:
                out[entry.name] = deck
        return out
    finally:
        col.close()


def test_apply_filtered_creates_decks(tmp_path: Path, fixture_with_filtered) -> None:
    out_dir = tmp_path / "gitified"
    export(deck_name="Top", out_dir=out_dir, profile=fixture_with_filtered.profile)

    # Build a fresh collection that has the parent decks but no filtered decks
    target = tmp_path / "target" / "collection.anki2"
    target.parent.mkdir(parents=True, exist_ok=True)
    col = Collection(str(target))
    try:
        col.decks.id("Top::Sub")
        col.decks.id("Top::Other")
        col.decks.id("Top::Cram")
    finally:
        col.close()

    report = apply_filtered(in_dir=out_dir, collection_path=target)
    assert sorted(report.created) == ["Top::Cram::All", "Top::Cram::Recent"]
    assert report.skipped == []
    assert report.conflicts == []

    fds = _filtered_decks(target)
    assert "Top::Cram::Recent" in fds
    assert "Top::Cram::All" in fds

    recent = fds["Top::Cram::Recent"]
    assert recent["resched"] is True
    assert recent["terms"] == [["deck:Top::Sub", 100, 0]]

    all_ = fds["Top::Cram::All"]
    assert all_["resched"] is False
    assert all_["terms"] == [["deck:Top::Other", 50, 5]]


def test_apply_filtered_is_idempotent(tmp_path: Path, fixture_with_filtered) -> None:
    out_dir = tmp_path / "gitified"
    export(deck_name="Top", out_dir=out_dir, profile=fixture_with_filtered.profile)

    target = tmp_path / "target" / "collection.anki2"
    target.parent.mkdir(parents=True, exist_ok=True)
    Collection(str(target)).close()

    r1 = apply_filtered(in_dir=out_dir, collection_path=target)
    r2 = apply_filtered(in_dir=out_dir, collection_path=target)

    assert sorted(r1.created) == ["Top::Cram::All", "Top::Cram::Recent"]
    assert r1.skipped == []
    assert r2.created == []
    assert sorted(r2.skipped) == ["Top::Cram::All", "Top::Cram::Recent"]
    assert r2.conflicts == []


def test_apply_filtered_conflicts_with_normal_deck(tmp_path: Path, fixture_with_filtered) -> None:
    out_dir = tmp_path / "gitified"
    export(deck_name="Top", out_dir=out_dir, profile=fixture_with_filtered.profile)

    target = tmp_path / "target" / "collection.anki2"
    target.parent.mkdir(parents=True, exist_ok=True)
    col = Collection(str(target))
    try:
        col.decks.id("Top::Cram::All")
    finally:
        col.close()

    report = apply_filtered(in_dir=out_dir, collection_path=target)
    assert report.conflicts == ["Top::Cram::All"]
    assert report.created == ["Top::Cram::Recent"]

    fds = _filtered_decks(target)
    assert "Top::Cram::All" not in fds
    assert "Top::Cram::Recent" in fds


def test_apply_filtered_dry_run_does_not_write(tmp_path: Path, fixture_with_filtered) -> None:
    out_dir = tmp_path / "gitified"
    export(deck_name="Top", out_dir=out_dir, profile=fixture_with_filtered.profile)

    target = tmp_path / "target" / "collection.anki2"
    target.parent.mkdir(parents=True, exist_ok=True)
    Collection(str(target)).close()

    report = apply_filtered(in_dir=out_dir, collection_path=target, dry_run=True)
    assert report.dry_run is True
    assert sorted(report.created) == ["Top::Cram::All", "Top::Cram::Recent"]
    assert _filtered_decks(target) == {}


def test_apply_filtered_no_filtered_yaml(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    target = tmp_path / "target" / "collection.anki2"
    target.parent.mkdir(parents=True, exist_ok=True)
    Collection(str(target)).close()

    with pytest.raises(FileNotFoundError):
        apply_filtered(in_dir=empty, collection_path=target)


def test_apply_filtered_empty_yaml_is_noop(tmp_path: Path, fixture_basic) -> None:
    """A gitified dir with no filtered decks emits an empty filtered_decks.yml.
    apply-filtered against it should be a clean no-op."""
    out_dir = tmp_path / "gitified"
    export(deck_name="Top", out_dir=out_dir, profile=fixture_basic.profile)

    target = tmp_path / "target" / "collection.anki2"
    target.parent.mkdir(parents=True, exist_ok=True)
    Collection(str(target)).close()

    report = apply_filtered(in_dir=out_dir, collection_path=target)
    assert report.created == []
    assert report.skipped == []
    assert report.conflicts == []


def test_apply_filtered_rejects_unknown_schema_version(tmp_path: Path) -> None:
    in_dir = tmp_path / "gitified"
    in_dir.mkdir()
    (in_dir / "filtered_decks.yml").write_text(
        "schema_version: 999\nfiltered_decks: []\n"
    )
    target = tmp_path / "target" / "collection.anki2"
    target.parent.mkdir(parents=True, exist_ok=True)
    Collection(str(target)).close()

    with pytest.raises(ValueError, match="schema_version"):
        apply_filtered(in_dir=in_dir, collection_path=target)


def test_cli_apply_filtered_end_to_end(tmp_path: Path, fixture_with_filtered) -> None:
    out_dir = tmp_path / "gitified"
    export(deck_name="Top", out_dir=out_dir, profile=fixture_with_filtered.profile)

    target = tmp_path / "target" / "collection.anki2"
    target.parent.mkdir(parents=True, exist_ok=True)
    Collection(str(target)).close()

    result = runner.invoke(
        app,
        ["apply-filtered", str(out_dir), "--collection", str(target)],
    )
    assert result.exit_code == 0, result.output
    assert "create=2" in result.output
    assert "Top::Cram::Recent" in result.output
    assert "Top::Cram::All" in result.output

    # Idempotent second run
    result2 = runner.invoke(
        app,
        ["apply-filtered", str(out_dir), "--collection", str(target)],
    )
    assert result2.exit_code == 0, result2.output
    assert "create=0" in result2.output
    assert "skipped=2" in result2.output


def test_cli_apply_filtered_dry_run(tmp_path: Path, fixture_with_filtered) -> None:
    out_dir = tmp_path / "gitified"
    export(deck_name="Top", out_dir=out_dir, profile=fixture_with_filtered.profile)

    target = tmp_path / "target" / "collection.anki2"
    target.parent.mkdir(parents=True, exist_ok=True)
    Collection(str(target)).close()

    result = runner.invoke(
        app,
        ["apply-filtered", str(out_dir), "--collection", str(target), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    assert _filtered_decks(target) == {}


def test_cli_apply_filtered_conflict_exits_2(tmp_path: Path, fixture_with_filtered) -> None:
    out_dir = tmp_path / "gitified"
    export(deck_name="Top", out_dir=out_dir, profile=fixture_with_filtered.profile)

    target = tmp_path / "target" / "collection.anki2"
    target.parent.mkdir(parents=True, exist_ok=True)
    col = Collection(str(target))
    try:
        col.decks.id("Top::Cram::All")
    finally:
        col.close()

    result = runner.invoke(
        app,
        ["apply-filtered", str(out_dir), "--collection", str(target)],
    )
    assert result.exit_code == 2, result.output
    assert "conflicts=1" in result.output
    assert "Top::Cram::All" in result.output


def test_apply_filtered_then_export_roundtrips_filtered_decks(
    tmp_path: Path,
    fixture_with_filtered,
) -> None:
    """apply-filtered into a fresh collection then re-export should reproduce
    the same filtered_decks.yml shape (modulo ordering, which is deterministic)."""
    out1 = tmp_path / "out1"
    export(deck_name="Top", out_dir=out1, profile=fixture_with_filtered.profile)

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    media_dir = target_dir / "collection.media"
    media_dir.mkdir()
    target = target_dir / "collection.anki2"
    col = Collection(str(target))
    try:
        col.decks.id("Top")
        col.decks.id("Top::Sub")
        col.decks.id("Top::Other")
    finally:
        col.close()

    apply_filtered(in_dir=out1, collection_path=target)

    from anki_gitify.profile import ProfilePaths
    fresh_profile = ProfilePaths(
        base=target_dir.parent,
        profile=target_dir.name,
        collection=target,
        media_dir=media_dir,
    )
    out2 = tmp_path / "out2"
    export(deck_name="Top", out_dir=out2, profile=fresh_profile)

    yml1 = (out1 / "filtered_decks.yml").read_text()
    yml2 = (out2 / "filtered_decks.yml").read_text()
    assert yml1 == yml2
