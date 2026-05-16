"""Helpers for `tests/test_diff.py`: build a deterministic base gitified tree
and apply named mutations to it.

A hand-built tree (not the conftest synthetic Collection fixture) is used so
note guids and other identifiers are stable across runs, which keeps the
golden JSON files in `tests/golden/diff/` reproducible.
"""

from __future__ import annotations

import csv
import io
import os
import subprocess
from pathlib import Path


GITIFY_YML = """\
anki_module_version: '24.0'
counts:
  card_overrides: 0
  cards: 3
  filtered_decks: 0
  media: 0
  normal_decks: 3
  notes: 3
  notetypes: 1
exported_at: '2026-01-01T00:00:00Z'
root_deck: Top
schema_version: 1
source_collection: collection.anki2
source_profile: test
tool_version: 0.3.0
"""

DECK_YML_ROOT = "description: ''\nname: Top\n"
DECK_YML_SUB = "description: ''\nname: Sub\n"
DECK_YML_OTHER = "description: ''\nname: Other\n"

NOTETYPE_META = """\
kind: normal
latex_post: ''
latex_pre: ''
name: Bidirectional
sort_field_index: 0
"""

NOTETYPE_FIELDS_YML = """\
- description: ''
  font: Arial
  name: Front
  plain_text: false
  rtl: false
  size: 20
  sticky: false
- description: ''
  font: Arial
  name: Back
  plain_text: false
  rtl: false
  size: 20
  sticky: false
"""

NOTETYPE_CSS = ".card { font-family: arial; }\n"

TEMPLATE_META = "name: Card 1\nordinal: 0\n"
TEMPLATE_FRONT = "{{Front}}\n"
TEMPLATE_BACK = "{{FrontSide}}<hr>{{Back}}\n"

FILTERED_YML_EMPTY = "filtered_decks: []\nschema_version: 1\n"


_BASE_NOTES = [
    ("NOTE_A", "Top::Sub", "alpha", "front a", "back a"),
    ("NOTE_B", "Top::Sub", "beta gamma", "front b", "back b"),
    ("NOTE_C", "Top::Other", "", "front c", "back c"),
]


def _render_notes_csv(rows: list[tuple[str, str, str, str, str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(["guid", "deck_path", "tags", "Front", "Back"])
    for r in sorted(rows, key=lambda r: (r[1], r[0])):
        w.writerow(r)
    return buf.getvalue()


def write_base_tree(out: Path) -> None:
    """Write the canonical hand-built gitified tree used as the diff base."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "gitify.yml").write_text(GITIFY_YML, encoding="utf-8", newline="\n")
    (out / "deck.yml").write_text(DECK_YML_ROOT, encoding="utf-8", newline="\n")

    sub = out / "decks" / "Sub"
    sub.mkdir(parents=True)
    (sub / "deck.yml").write_text(DECK_YML_SUB, encoding="utf-8", newline="\n")

    other = out / "decks" / "Other"
    other.mkdir(parents=True)
    (other / "deck.yml").write_text(DECK_YML_OTHER, encoding="utf-8", newline="\n")

    nt = out / "notetypes" / "bidirectional"
    nt.mkdir(parents=True)
    (nt / "meta.yml").write_text(NOTETYPE_META, encoding="utf-8", newline="\n")
    (nt / "fields.yml").write_text(NOTETYPE_FIELDS_YML, encoding="utf-8", newline="\n")
    (nt / "style.css").write_text(NOTETYPE_CSS, encoding="utf-8", newline="\n")

    tmpl = nt / "templates" / "00-card-1"
    tmpl.mkdir(parents=True)
    (tmpl / "meta.yml").write_text(TEMPLATE_META, encoding="utf-8", newline="\n")
    (tmpl / "front.html").write_text(TEMPLATE_FRONT, encoding="utf-8", newline="\n")
    (tmpl / "back.html").write_text(TEMPLATE_BACK, encoding="utf-8", newline="\n")

    (out / "notes").mkdir()
    (out / "notes" / "bidirectional.csv").write_text(
        _render_notes_csv(_BASE_NOTES), encoding="utf-8", newline="\n"
    )

    (out / "filtered_decks.yml").write_text(
        FILTERED_YML_EMPTY, encoding="utf-8", newline="\n"
    )


_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "diff-test",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "diff-test",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        check=True,
    )


def init_and_commit(repo: Path, message: str = "init") -> str:
    """Init a git repo at `repo` and commit everything in it. Return the sha."""
    git(repo, "init", "-q", "--initial-branch=main")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


# ---------- Named mutators ----------


def _rewrite_notes_csv(repo: Path, rows: list[tuple[str, str, str, str, str]]) -> None:
    (repo / "notes" / "bidirectional.csv").write_text(
        _render_notes_csv(rows), encoding="utf-8", newline="\n"
    )


def mutator_tag_added(repo: Path) -> None:
    rows = list(_BASE_NOTES)
    rows[0] = ("NOTE_A", "Top::Sub", "alpha covered", "front a", "back a")
    _rewrite_notes_csv(repo, rows)


def mutator_tag_removed(repo: Path) -> None:
    rows = list(_BASE_NOTES)
    rows[1] = ("NOTE_B", "Top::Sub", "beta", "front b", "back b")  # drop "gamma"
    _rewrite_notes_csv(repo, rows)


def mutator_field_edited(repo: Path) -> None:
    rows = list(_BASE_NOTES)
    rows[0] = ("NOTE_A", "Top::Sub", "alpha", "front a EDITED", "back a")
    _rewrite_notes_csv(repo, rows)


def mutator_note_moved(repo: Path) -> None:
    rows = list(_BASE_NOTES)
    rows[0] = ("NOTE_A", "Top::Other", "alpha", "front a", "back a")
    _rewrite_notes_csv(repo, rows)


def mutator_note_added(repo: Path) -> None:
    rows = list(_BASE_NOTES) + [
        ("NOTE_D", "Top::Sub", "newtag", "front d", "back d"),
    ]
    _rewrite_notes_csv(repo, rows)


def mutator_note_removed(repo: Path) -> None:
    rows = [r for r in _BASE_NOTES if r[0] != "NOTE_C"]
    _rewrite_notes_csv(repo, rows)


def mutator_notetype_field_added(repo: Path) -> None:
    """Add a 'Notes' field to the Bidirectional notetype + update CSV header/rows."""
    nt_fields_path = repo / "notetypes" / "bidirectional" / "fields.yml"
    nt_fields_path.write_text(
        NOTETYPE_FIELDS_YML
        + "- description: ''\n"
        + "  font: Arial\n"
        + "  name: Notes\n"
        + "  plain_text: false\n"
        + "  rtl: false\n"
        + "  size: 20\n"
        + "  sticky: false\n",
        encoding="utf-8",
        newline="\n",
    )
    # Rewrite the CSV with the new column at position 5.
    csv_path = repo / "notes" / "bidirectional.csv"
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(["guid", "deck_path", "tags", "Front", "Back", "Notes"])
    for r in sorted(_BASE_NOTES, key=lambda r: (r[1], r[0])):
        w.writerow(list(r) + [""])
    csv_path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")


def mutator_template_edited(repo: Path) -> None:
    front = repo / "notetypes" / "bidirectional" / "templates" / "00-card-1" / "front.html"
    front.write_text("<b>{{Front}}</b>\n", encoding="utf-8", newline="\n")


def mutator_css_edited(repo: Path) -> None:
    css = repo / "notetypes" / "bidirectional" / "style.css"
    css.write_text(".card { font-family: serif; color: blue; }\n", encoding="utf-8", newline="\n")


def mutator_deck_added(repo: Path) -> None:
    new_deck = repo / "decks" / "Sub" / "decks" / "Leaf"
    new_deck.mkdir(parents=True)
    (new_deck / "deck.yml").write_text(
        "description: ''\nname: Leaf\n", encoding="utf-8", newline="\n"
    )


def mutator_filtered_added(repo: Path) -> None:
    (repo / "filtered_decks.yml").write_text(
        """\
filtered_decks:
  - delays: null
    name: Top::Cram
    resched: true
    terms:
      - limit: 100
        order: 0
        search: 'deck:Top is:due'
""",
        encoding="utf-8",
        newline="\n",
    )
    # Also write FILTERED_DECKS.md so `verify` would pass — not strictly
    # required by the diff but keeps the tree internally consistent.
    (repo / "FILTERED_DECKS.md").write_text(
        "# Filtered decks\n", encoding="utf-8", newline="\n"
    )


def mutator_media_added(repo: Path) -> None:
    media = repo / "media"
    media.mkdir(exist_ok=True)
    (media / "sun.png").write_bytes(b"\x89PNG-fake-bytes")
