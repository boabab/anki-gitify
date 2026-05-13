"""Unit tests for the textconv humanizer."""

from __future__ import annotations

from anki_gitify.textconv import humanize_bytes


def _csv(rows: list[list[str]]) -> bytes:
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def test_notes_csv_basic_rendering() -> None:
    data = _csv(
        [
            ["guid", "deck_path", "tags", "Front", "Back"],
            ["abc", "Top::Sub", "kanji n5", "front-content", "back-content"],
        ]
    )
    out = humanize_bytes(data)
    assert "== note abc ==" in out
    assert "deck: Top::Sub" in out
    assert "tags:" in out
    assert "  - kanji" in out
    assert "  - n5" in out
    assert "-- field: Front --" in out
    assert "front-content" in out
    assert "-- field: Back --" in out
    assert "back-content" in out


def test_notes_csv_sorts_by_guid_for_stable_diffs() -> None:
    """Sorting by guid (not deck_path) means a deck move shows as one line, not a relocation."""
    data = _csv(
        [
            ["guid", "deck_path", "tags", "F"],
            ["zzz", "Top::A", "", "second"],
            ["aaa", "Top::B", "", "first"],
        ]
    )
    out = humanize_bytes(data)
    aaa_pos = out.index("== note aaa ==")
    zzz_pos = out.index("== note zzz ==")
    assert aaa_pos < zzz_pos


def test_notes_csv_sorts_tags_alphabetically() -> None:
    """Sorted tags mean an added tag inserts in place rather than reordering."""
    data = _csv(
        [
            ["guid", "deck_path", "tags", "F"],
            ["g", "D", "zebra alpha mango", "x"],
        ]
    )
    out = humanize_bytes(data)
    lines = [ln for ln in out.splitlines() if ln.startswith("  - ")]
    assert lines == ["  - alpha", "  - mango", "  - zebra"]


def test_notes_csv_empty_tags() -> None:
    data = _csv(
        [
            ["guid", "deck_path", "tags", "F"],
            ["g", "D", "", "x"],
        ]
    )
    out = humanize_bytes(data)
    assert "tags: []" in out


def test_notes_csv_multiline_field_preserved() -> None:
    data = _csv(
        [
            ["guid", "deck_path", "tags", "Body"],
            ["g", "D", "", "line1\nline2\nline3"],
        ]
    )
    out = humanize_bytes(data)
    assert "line1\nline2\nline3" in out


def test_notes_csv_html_field_not_escaped() -> None:
    """HTML in fields should appear verbatim (no YAML quoting noise)."""
    data = _csv(
        [
            ["guid", "deck_path", "tags", "F"],
            ["g", "D", "", '<img src="sun.png">'],
        ]
    )
    out = humanize_bytes(data)
    assert '<img src="sun.png">' in out


def test_cards_csv_rendering() -> None:
    data = _csv(
        [
            ["note_guid", "ord", "deck_path"],
            ["g1", "1", "Top::B"],
            ["g0", "0", "Top::A"],
        ]
    )
    out = humanize_bytes(data)
    g0_pos = out.index("note=g0")
    g1_pos = out.index("note=g1")
    assert g0_pos < g1_pos
    assert "ord=0" in out
    assert "ord=1" in out
    assert "deck=Top::A" in out


def test_unknown_format_passes_through() -> None:
    data = b"hello,world\n1,2\n"
    out = humanize_bytes(data)
    assert out == "hello,world\n1,2\n"


def test_empty_input_passes_through() -> None:
    assert humanize_bytes(b"") == ""


def test_added_tag_produces_minimal_diff() -> None:
    """Sanity-check the whole point of this exercise: adding a tag is a single inserted line."""
    before = humanize_bytes(
        _csv(
            [
                ["guid", "deck_path", "tags", "F"],
                ["g", "D", "alpha mango", "x"],
            ]
        )
    )
    after = humanize_bytes(
        _csv(
            [
                ["guid", "deck_path", "tags", "F"],
                ["g", "D", "alpha mango zebra", "x"],
            ]
        )
    )
    import difflib

    diff = list(
        difflib.unified_diff(before.splitlines(), after.splitlines(), n=0, lineterm="")
    )
    # one hunk header + one insertion line
    insertions = [ln for ln in diff if ln.startswith("+") and not ln.startswith("+++")]
    deletions = [ln for ln in diff if ln.startswith("-") and not ln.startswith("---")]
    assert insertions == ["+  - zebra"], diff
    assert deletions == [], diff


def test_deck_move_produces_one_line_diff() -> None:
    before = humanize_bytes(
        _csv(
            [
                ["guid", "deck_path", "tags", "F"],
                ["g", "Top::A", "", "x"],
            ]
        )
    )
    after = humanize_bytes(
        _csv(
            [
                ["guid", "deck_path", "tags", "F"],
                ["g", "Top::B", "", "x"],
            ]
        )
    )
    import difflib

    diff = list(
        difflib.unified_diff(before.splitlines(), after.splitlines(), n=0, lineterm="")
    )
    insertions = [ln for ln in diff if ln.startswith("+") and not ln.startswith("+++")]
    deletions = [ln for ln in diff if ln.startswith("-") and not ln.startswith("---")]
    assert insertions == ["+deck: Top::B"]
    assert deletions == ["-deck: Top::A"]
