"""Full round-trip test: export → import (.apkg) → reimport into fresh
collection → re-export → diff. Empty diff = no information loss within v1's
scope (notes, notetypes, deck tree, media, deck_path, no filtered decks).
"""

from __future__ import annotations

import filecmp
from pathlib import Path

from anki_gitify.export.exporter import export
from anki_gitify.importer.importer import import_ as run_import


def _diff_dirs(a: Path, b: Path, *, ignore: set[str]) -> list[str]:
    """Recursively compare two directories. Return list of differing relative paths."""
    diffs: list[str] = []

    def _walk(rel: Path) -> None:
        ap = a / rel
        bp = b / rel
        a_entries = {p.name for p in ap.iterdir()} if ap.is_dir() else set()
        b_entries = {p.name for p in bp.iterdir()} if bp.is_dir() else set()
        all_entries = (a_entries | b_entries) - ignore
        for name in sorted(all_entries):
            sub_rel = rel / name
            sub_a = a / sub_rel
            sub_b = b / sub_rel
            if sub_a.is_dir() and sub_b.is_dir():
                _walk(sub_rel)
            elif sub_a.is_file() and sub_b.is_file():
                if not filecmp.cmp(sub_a, sub_b, shallow=False):
                    diffs.append(str(sub_rel))
            else:
                diffs.append(f"presence-mismatch: {sub_rel}")

    _walk(Path("."))
    return diffs


def test_full_round_trip(tmp_path: Path, fixture_basic, reimport_collection) -> None:
    # Export #1
    out1 = tmp_path / "out1"
    r1 = export(deck_name="Top", out_dir=out1, profile=fixture_basic.profile)
    assert r1.notes == 6
    assert not r1.has_card_overrides

    # Build .apkg
    apkg = tmp_path / "roundtrip.apkg"
    report, _ = run_import(in_dir=out1, out_apkg=apkg)
    assert report.notes == 6
    assert apkg.is_file()

    # Reimport into a fresh empty Collection
    fresh = reimport_collection(apkg)

    # Re-export the fresh Collection
    out2 = tmp_path / "out2"
    r2 = export(deck_name="Top", out_dir=out2, profile=fresh)
    assert r2.notes == r1.notes

    # Diff the two gitified trees, ignoring volatile metadata
    diffs = _diff_dirs(out1, out2, ignore={"gitify.yml"})
    assert diffs == [], f"round-trip mismatch: {diffs}"


def test_round_trip_preserves_guids(tmp_path: Path, fixture_basic, reimport_collection) -> None:
    import csv

    out1 = tmp_path / "out1"
    export(deck_name="Top", out_dir=out1, profile=fixture_basic.profile)
    apkg = tmp_path / "roundtrip.apkg"
    run_import(in_dir=out1, out_apkg=apkg)
    fresh = reimport_collection(apkg)
    out2 = tmp_path / "out2"
    export(deck_name="Top", out_dir=out2, profile=fresh)

    def _guids(d: Path) -> set[str]:
        out: set[str] = set()
        for csv_path in (d / "notes").glob("*.csv"):
            with csv_path.open() as fh:
                reader = csv.reader(fh)
                next(reader)
                for row in reader:
                    out.add(row[0])
        return out

    assert _guids(out1) == _guids(out2)


def test_round_trip_preserves_media(tmp_path: Path, fixture_basic, reimport_collection) -> None:
    out1 = tmp_path / "out1"
    export(deck_name="Top", out_dir=out1, profile=fixture_basic.profile)
    apkg = tmp_path / "roundtrip.apkg"
    run_import(in_dir=out1, out_apkg=apkg)
    fresh = reimport_collection(apkg)
    out2 = tmp_path / "out2"
    export(deck_name="Top", out_dir=out2, profile=fresh)

    media1 = sorted(p.name for p in (out1 / "media").iterdir())
    media2 = sorted(p.name for p in (out2 / "media").iterdir())
    assert media1 == media2 == ["hello.mp3", "sun.png"]
