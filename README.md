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
```

The user's Anki must be **closed** when running `export` (the collection.anki2 file is locked otherwise).

## Filtered decks

Filtered decks are preserved in `filtered_decks.yml` (canonical) + `FILTERED_DECKS.md` (auto-generated human view). The `.apkg` produced by `import` contains only normal decks — `genanki` has no filtered-deck primitive. After importing, recreate filtered decks via Tools → Create Filtered Deck (or wait for v2's `apply-filtered`).

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
