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

# Semantic diff of two revisions of the gitified deck
anki-gitify diff                                  # HEAD vs working tree
anki-gitify diff main feature                     # any two refs
anki-gitify diff --repo /path/to/gitified --format markdown   # report for a PR

# Apply filtered-deck definitions to your live collection (v2)
anki-gitify apply-filtered /path/to/japanese-gitified
anki-gitify apply-filtered /path/to/japanese-gitified --dry-run
```

The user's Anki must be **closed** when running `export` or `apply-filtered` (the collection.anki2 file is locked otherwise).

## Semantic diff

`anki-gitify diff` correlates notes between two revisions of a gitified deck by GUID and prints a per-entity report instead of a raw CSV diff:

- which notes had tags added/removed
- which cards moved between decks
- which note fields changed (with an inline text diff)
- which notetype templates/CSS were edited
- which filtered decks, deck paths, or media files appeared/disappeared

Default: compares `HEAD` against the working tree (useful right after re-exporting from Anki). With one ref it compares that ref against the working tree; with two refs it compares the two refs directly. `--format markdown` produces a shareable report; `--format json` emits the same structure for scripting.

The gitified directory can live at the repo root or in a subdirectory of a larger repo — point `--repo` at it.

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
