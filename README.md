# anki-gitify

Convert an Anki deck (with subdecks) into a git-versionable directory of plain text, and back into an importable `.apkg`.

## What it preserves
- Notes (fields, tags, GUIDs)
- Note types: fields, CSS, all card templates (front/back HTML)
- Deck hierarchy + per-note home deck path
- Filtered deck definitions (search strings, order, limits)
- Media files referenced from notes/templates

## What it does NOT preserve (v1)
- Scheduling state (due dates, intervals, ease, lapses)
- Review log

## Install

`anki` (PyPI) lags the newest Python. This project pins `>=3.11,<3.14`. Python 3.13 is recommended; 3.14 wheels for `anki` are not yet published.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

[uv](https://github.com/astral-sh/uv) works equivalently if you prefer it.

## Usage

```bash
# List decks in your collection
anki-gitify list-decks

# Export a deck
anki-gitify export "Japanese" /path/to/japanese-gitified

# Import back into a .apkg you can open with Anki's File → Import
anki-gitify import /path/to/japanese-gitified japanese.apkg

# Validate a gitified directory (no Anki needed)
anki-gitify verify /path/to/japanese-gitified

# Apply filtered-deck definitions to your live collection (v2)
anki-gitify apply-filtered /path/to/japanese-gitified
anki-gitify apply-filtered /path/to/japanese-gitified --dry-run
```

The user's Anki must be **closed** when running `export` or `apply-filtered` (the collection.anki2 file is locked otherwise).

## Humanized git diffs

The exported `notes/<notetype>.csv` is one wide row per note, so even small Anki edits (a renamed tag, a moved card, a tweaked field) show up in raw `git diff` as opaque single-line CSV rewrites. Wire up a textconv driver to render those files as one block per note instead:

```bash
cd /path/to/your-gitified-deck
anki-gitify install-diff-driver
```

This is idempotent: it appends a marker block to `.gitattributes` and runs `git config diff.anki-gitify.textconv "<path>/anki-gitify textconv"` in the enclosing repo. After it, plain `git diff`, `git log -p`, `git show`, and IDE diff views render notes/cards CSVs like:

```
== note abc123 ==
deck: Japanese::Vocab::Kanji
tags:
  - kanji
  - n5

-- field: Front --
日

-- field: Back --
sun, day
```

So tagging a note shows up as one inserted `  - <tag>` line, moving a card is a single `deck:` edit, and a field rewrite is a normal multi-line text diff scoped to that field. Other files are untouched.

`anki-gitify install-diff-driver --uninstall` removes both the `.gitattributes` block and the git-config entry. **Note**: GitHub's web PR view doesn't run textconv drivers; this only improves your local tooling.

## Filtered decks

Filtered decks are preserved in `filtered_decks.yml` (canonical) + `FILTERED_DECKS.md` (auto-generated human view). The `.apkg` produced by `import` contains only normal decks — `genanki` has no filtered-deck primitive. After importing the `.apkg`, run `anki-gitify apply-filtered <gitified-dir>` to recreate the filtered decks in your collection (or recreate them by hand via Tools → Create Filtered Deck).

`apply-filtered` is **idempotent**: filtered decks that already exist with the same name are skipped. If a *normal* deck already has that name it's reported as a conflict and skipped (the command exits 2) — resolve manually before re-running.

## Filtered deck order enum

`order` field in `filtered_decks.yml` mirrors Anki's internal enum:

| Value | Meaning |
|---:|---|
| 0 | Oldest seen first |
| 1 | Random |
| 2 | Most lapses first |
| 3 | Added order |
| 4 | Due date |
| 5 | Most retrievable |
| 6 | Reverse added order |
| 7 | Lowest interval first |
| 8 | Highest interval first |
| 9 | Lowest ease first |
| 10 | Highest ease first |

## Important note about scheduling

Editing field/template structure (adding fields, changing template count, renaming the notetype) and re-importing will trigger Anki's "schema modification" path on import, which **resets scheduling on existing cards**. Editing only field *content*, CSS, or template HTML is safe — scheduling is preserved (notes are matched by GUID).

## Development

```bash
.venv/bin/pytest
```

## Project layout & design

- [docs/DESIGN.md](docs/DESIGN.md) — the living spec: on-disk format, export/import algorithms, filtered-deck handling, round-trip determinism rules. Read this before contributing non-trivial changes.
- [CLAUDE.md](CLAUDE.md) — agent-facing rules and conventions (Claude Code reads it automatically; useful as a contributor primer too).
- `src/anki_gitify/schema.py` — pydantic models defining the on-disk format contract.
- `tests/test_roundtrip.py` — executable spec of round-trip safety. If this goes red, docs and code disagree.

When you change the on-disk format, bump `SCHEMA_VERSION` in `schema.py` and update `docs/DESIGN.md` in the same commit.
