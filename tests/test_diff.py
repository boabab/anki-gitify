"""Unit tests for the semantic diff over two LoadedRepo snapshots."""

from __future__ import annotations

from pathlib import Path

from anki_gitify.diff import compute_diff, render_json, render_markdown
from anki_gitify.importer.loader import (
    LoadedCardOverride,
    LoadedDeckTree,
    LoadedField,
    LoadedNote,
    LoadedNoteType,
    LoadedRepo,
    LoadedTemplate,
)
from anki_gitify.schema import FilteredDecksFile


def _nt(slug: str = "bidirectional", name: str = "Bidirectional") -> LoadedNoteType:
    return LoadedNoteType(
        slug=slug,
        name=name,
        kind="normal",
        sort_field_index=0,
        latex_pre="",
        latex_post="",
        fields=[LoadedField(name="Front"), LoadedField(name="Back")],
        css=".card { color: black; }",
        templates=[
            LoadedTemplate(
                name="Front->Back",
                ordinal=0,
                qfmt="{{Front}}",
                afmt="{{FrontSide}}<hr>{{Back}}",
            ),
        ],
    )


def _note(guid: str, deck: str, tags: list[str], fields: list[str], slug: str = "bidirectional") -> LoadedNote:
    return LoadedNote(notetype_slug=slug, guid=guid, deck_path=deck, tags=tags, fields=fields)


def _repo(notes: list[LoadedNote], notetypes: list[LoadedNoteType] | None = None, **kw) -> LoadedRepo:
    return LoadedRepo(
        in_dir=Path("/tmp/fake"),
        gitify={"schema_version": 1, "root_deck": "Top"},
        notetypes=notetypes if notetypes is not None else [_nt()],
        notes=notes,
        card_overrides=kw.get("card_overrides", []),
        deck_tree=kw.get("deck_tree", LoadedDeckTree(root_name="Top", full_paths=["Top"])),
        filtered=kw.get("filtered", FilteredDecksFile()),
        media_files=kw.get("media_files", []),
    )


def test_empty_diff_for_identical_repos() -> None:
    notes = [_note("g1", "Top::A", ["x"], ["F", "B"])]
    diff = compute_diff(_repo(notes), _repo(notes))
    assert diff.is_empty()


def test_tag_added() -> None:
    a = _repo([_note("g1", "Top::A", ["x"], ["F", "B"])])
    b = _repo([_note("g1", "Top::A", ["x", "y"], ["F", "B"])])
    diff = compute_diff(a, b)
    assert not diff.is_empty()
    assert len(diff.notes.changed) == 1
    nc = diff.notes.changed[0]
    assert nc.guid == "g1"
    assert nc.tags_added == ["y"]
    assert nc.tags_removed == []


def test_tag_removed() -> None:
    a = _repo([_note("g1", "Top::A", ["x", "y"], ["F", "B"])])
    b = _repo([_note("g1", "Top::A", ["y"], ["F", "B"])])
    diff = compute_diff(a, b)
    nc = diff.notes.changed[0]
    assert nc.tags_removed == ["x"]
    assert nc.tags_added == []


def test_deck_move() -> None:
    a = _repo([_note("g1", "Top::A", [], ["F", "B"])])
    b = _repo([_note("g1", "Top::B", [], ["F", "B"])])
    diff = compute_diff(a, b)
    nc = diff.notes.changed[0]
    assert nc.deck_path_before == "Top::A"
    assert nc.deck_path_after == "Top::B"


def test_field_edit() -> None:
    a = _repo([_note("g1", "Top::A", [], ["sun", "B"])])
    b = _repo([_note("g1", "Top::A", [], ["moon", "B"])])
    diff = compute_diff(a, b)
    nc = diff.notes.changed[0]
    assert len(nc.fields_changed) == 1
    fc = nc.fields_changed[0]
    assert fc.name == "Front"
    assert fc.before == "sun"
    assert fc.after == "moon"


def test_note_added() -> None:
    a = _repo([_note("g1", "Top::A", [], ["F", "B"])])
    b = _repo([
        _note("g1", "Top::A", [], ["F", "B"]),
        _note("g2", "Top::B", [], ["F2", "B2"]),
    ])
    diff = compute_diff(a, b)
    assert len(diff.notes.added) == 1
    assert diff.notes.added[0].guid == "g2"
    assert diff.notes.added[0].deck_path == "Top::B"
    assert diff.notes.added[0].label == "F2"


def test_note_removed() -> None:
    a = _repo([
        _note("g1", "Top::A", [], ["F", "B"]),
        _note("g2", "Top::B", [], ["F2", "B2"]),
    ])
    b = _repo([_note("g1", "Top::A", [], ["F", "B"])])
    diff = compute_diff(a, b)
    assert len(diff.notes.removed) == 1
    assert diff.notes.removed[0].guid == "g2"


def test_notetype_migration() -> None:
    a = _repo(
        [_note("g1", "Top::A", [], ["F", "B"], slug="bidirectional")],
        notetypes=[_nt("bidirectional", "Bidirectional"), _nt("cloze1", "Cloze1")],
    )
    b = _repo(
        [_note("g1", "Top::A", [], ["F", "B"], slug="cloze1")],
        notetypes=[_nt("bidirectional", "Bidirectional"), _nt("cloze1", "Cloze1")],
    )
    diff = compute_diff(a, b)
    assert len(diff.notes.migrated_notetype) == 1
    mig = diff.notes.migrated_notetype[0]
    assert mig.from_slug == "bidirectional"
    assert mig.to_slug == "cloze1"
    # not also reported as add+remove
    assert diff.notes.added == []
    assert diff.notes.removed == []


def test_notetype_added_and_removed() -> None:
    a = _repo([], notetypes=[_nt("bidirectional", "Bidirectional")])
    b = _repo([], notetypes=[_nt("cloze1", "Cloze1")])
    diff = compute_diff(a, b)
    assert diff.notetypes.added == ["Cloze1"]
    assert diff.notetypes.removed == ["Bidirectional"]


def test_notetype_template_html_changed() -> None:
    nt_a = _nt()
    nt_b = _nt()
    nt_b.templates[0].qfmt = "{{Front}} updated"
    diff = compute_diff(
        _repo([], notetypes=[nt_a]),
        _repo([], notetypes=[nt_b]),
    )
    assert len(diff.notetypes.changed) == 1
    nc = diff.notetypes.changed[0]
    assert nc.name == "Bidirectional"
    assert len(nc.templates_changed) == 1
    tc = nc.templates_changed[0]
    assert tc.qfmt_changed
    assert "updated" in tc.qfmt_diff


def test_notetype_css_changed() -> None:
    nt_a = _nt()
    nt_b = _nt()
    nt_b.css = ".card { color: red; }"
    diff = compute_diff(
        _repo([], notetypes=[nt_a]),
        _repo([], notetypes=[nt_b]),
    )
    nc = diff.notetypes.changed[0]
    assert nc.css_changed
    assert "color: red" in nc.css_diff


def test_field_renamed() -> None:
    nt_a = _nt()
    nt_b = _nt()
    nt_b.fields[1] = LoadedField(name="Reverse")
    diff = compute_diff(
        _repo([], notetypes=[nt_a]),
        _repo([], notetypes=[nt_b]),
    )
    nc = diff.notetypes.changed[0]
    assert nc.fields_renamed == [["Back", "Reverse"]]
    assert nc.fields_added == []
    assert nc.fields_removed == []


def test_deck_tree_added() -> None:
    a = _repo([])
    b = _repo(
        [],
        deck_tree=LoadedDeckTree(root_name="Top", full_paths=["Top", "Top::New"]),
    )
    diff = compute_diff(a, b)
    assert diff.deck_tree.added == ["Top::New"]


def test_media_added_and_removed() -> None:
    a = _repo([], media_files=[Path("/x/sun.png"), Path("/x/old.mp3")])
    b = _repo([], media_files=[Path("/x/sun.png"), Path("/x/new.mp3")])
    diff = compute_diff(a, b)
    assert diff.media.added == ["new.mp3"]
    assert diff.media.removed == ["old.mp3"]


def test_card_override_added() -> None:
    a = _repo([_note("g1", "Top::A", [], ["F", "B"])])
    b = _repo(
        [_note("g1", "Top::A", [], ["F", "B"])],
        card_overrides=[LoadedCardOverride(note_guid="g1", ord=1, deck_path="Top::B")],
    )
    diff = compute_diff(a, b)
    assert len(diff.notes.changed) == 1
    nc = diff.notes.changed[0]
    assert len(nc.card_overrides_changed) == 1
    ov = nc.card_overrides_changed[0]
    assert ov.ord == 1
    assert ov.before is None
    assert ov.after == "Top::B"


def test_label_truncates_long_field_and_strips_html() -> None:
    long_html = '<b>kanji</b> ' + 'x' * 100
    a = _repo([_note("g1", "Top::A", [], ["", ""])])
    b = _repo([_note("g1", "Top::A", [], [long_html, ""])])
    diff = compute_diff(a, b)
    nc = diff.notes.changed[0]
    assert "<b>" not in nc.label
    assert nc.label.endswith("...")
    assert len(nc.label) <= 40


def test_render_json_is_serializable() -> None:
    """asdict must yield JSON-serializable output for every kind of change."""
    nt_a = _nt()
    nt_b = _nt()
    nt_b.css = "changed"
    a = _repo([_note("g1", "Top::A", ["x"], ["sun", "B"])], notetypes=[nt_a])
    b = _repo(
        [_note("g1", "Top::B", ["x", "new"], ["moon", "B"])],
        notetypes=[nt_b],
    )
    diff = compute_diff(a, b)
    import json

    parsed = json.loads(render_json(diff))
    assert parsed["notes"]["changed"][0]["guid"] == "g1"
    assert parsed["notes"]["changed"][0]["tags_added"] == ["new"]


def test_render_markdown_basic() -> None:
    a = _repo([_note("g1", "Top::A", [], ["F", "B"])])
    b = _repo([_note("g1", "Top::A", ["new"], ["F", "B"])])
    diff = compute_diff(a, b)
    out = render_markdown(diff)
    assert "## Summary" in out
    assert "## Notes" in out
    assert "tags added:   new" in out


def test_render_markdown_empty() -> None:
    a = _repo([_note("g1", "Top::A", [], ["F", "B"])])
    diff = compute_diff(a, a)
    out = render_markdown(diff)
    assert "No semantic changes." in out


def test_diff_is_symmetric_in_structure() -> None:
    """A->B's added must equal B->A's removed (and vice versa)."""
    a = _repo([_note("g1", "Top::A", ["x"], ["F", "B"])])
    b = _repo([
        _note("g1", "Top::A", ["x"], ["F", "B"]),
        _note("g2", "Top::B", [], ["F2", "B2"]),
    ])
    ab = compute_diff(a, b)
    ba = compute_diff(b, a)
    assert [n.guid for n in ab.notes.added] == [n.guid for n in ba.notes.removed]
