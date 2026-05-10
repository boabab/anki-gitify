# CLAUDE.md

Guidance for AI agents (Claude Code, Cursor, etc.) working in this repo. Humans should read [README.md](README.md) first; the deep spec lives in [docs/DESIGN.md](docs/DESIGN.md).

## What this project is

`anki-gitify` is a Python CLI that converts an Anki deck (with subdecks) into a git-versionable directory of plain-text files, and back into an importable `.apkg`. v1 preserves notes/notetypes/templates/CSS/media/filtered-deck definitions; it does **not** preserve scheduling state or review history.

## Run, test, and develop

The project uses a **local virtualenv** at `.venv/` (Python 3.13). Always use it — never install or run with system Python.

```bash
.venv/bin/pytest                      # run all tests
.venv/bin/pytest tests/test_roundtrip.py -v
.venv/bin/anki-gitify --help          # CLI surface
.venv/bin/anki-gitify list-decks      # smoke test against the user's collection (Anki must be closed)
```

If the venv is missing, recreate it:
```bash
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## Where things live

- [src/anki_gitify/schema.py](src/anki_gitify/schema.py) — pydantic contract for the on-disk format. The shared types both halves consume. **Bump `SCHEMA_VERSION` here for any backward-incompatible format change.**
- [src/anki_gitify/export/](src/anki_gitify/export/) — orchestrator + per-entity emitters (`exporter.py`, `decks.py`, `notetypes.py`, `cards.py`, `notes.py`, `filtered.py`, `media.py`).
- [src/anki_gitify/importer/](src/anki_gitify/importer/) — `loader.py` parses gitified dirs, `genanki_build.py` produces `.apkg`, `apply_filtered.py` writes filtered-deck metadata back into a live collection (v2).
- [src/anki_gitify/cli.py](src/anki_gitify/cli.py) — typer entry point: `list-decks`, `export`, `import`, `verify`, `apply-filtered`.
- [tests/conftest.py](tests/conftest.py) — synthetic fixtures (`fixture_basic`, `fixture_with_filtered`) built via `anki.collection.Collection`. Don't run tests against the user's real collection.

## Source-of-truth pointers

- **The on-disk format** is specified in [docs/DESIGN.md](docs/DESIGN.md). Read it before changing anything in `export/` or `importer/`.
- **The CLI flags** are documented by `--help` output. Don't duplicate flag tables in markdown.
- **Round-trip behavior** is pinned by [tests/test_roundtrip.py](tests/test_roundtrip.py). If a change breaks it, fix the change — not the test — unless the format spec is intentionally evolving.

## Hard rules (the things that bite)

1. **Never write directly to a live `collection.anki2` from the import path.** v1 produces a `.apkg` via `genanki`; the user imports it manually. The only exception is the v2 `apply-filtered` subcommand, which only writes filtered-deck *metadata*.
2. **Always preserve `notes.guid` on round-trip.** Anki dedups by GUID — losing it means duplicates and lost scheduling on the user's live collection.
3. **Home deck of a card is `odid if odid > 0 else did`** — never the current `did` when the card is sitting in a filtered deck. Get this wrong and exports become non-deterministic depending on whether a filter was rebuilt.
4. **Output must be deterministic.** Sorted directory iteration; CSV rows sorted by `(deck_path, guid)`; `yaml.safe_dump(sort_keys=True)`; LF newlines everywhere; HTML/CSS written verbatim. Re-running export on the same collection must produce a byte-identical tree (modulo `gitify.yml.exported_at`).
5. **Bump `SCHEMA_VERSION` and update `docs/DESIGN.md` in the same commit** for any backward-incompatible on-disk format change. v2 must still be able to read v1 repos.
6. **Reject filtered decks as export roots.** They have no notes of their own. The export command errors with a pointer at home decks.
7. **`cards.csv` is lossy on import in v1.** If present, refuse unless `--ignore-card-overrides` is passed. Do not silently collapse divergent decks.

## Conventions

- **Python**: 3.11–3.13 (`anki` PyPI lags newest Pythons; 3.14 wheels not yet published). Project venv uses 3.13.
- **Pydantic models in `schema.py`** are the validation contract; modules don't redefine field shapes.
- **The typer CLI tests** ([tests/test_cli.py](tests/test_cli.py)) are the canonical example for end-to-end behavior — copy that pattern when adding a subcommand.
- **No comments explaining what code does**; only comments for non-obvious *why*. Readable identifiers and short functions over docstrings.
- **Don't add abstractions for hypothetical v2 features.** v2 has explicit `--lossless` and `apply-filtered` plans documented in `docs/DESIGN.md`; don't pre-emptively scaffold them.

## When the user asks for a non-trivial change

1. Read [docs/DESIGN.md](docs/DESIGN.md) first.
2. Check the round-trip test still passes after your change: `.venv/bin/pytest tests/test_roundtrip.py`.
3. If the on-disk format changed, update `docs/DESIGN.md` and bump `SCHEMA_VERSION` in the same commit.
4. If a CLI flag was added or renamed, update [README.md](README.md) usage examples.

## Things to avoid

- Sphinx, MkDocs, GitHub wiki, auto-generated API docs — out of scope.
- Adding `CHANGELOG.md` or `CONTRIBUTING.md` until they're needed.
- Running tests or commands against the user's real Anki collection without explicit instruction.
- Bypassing the venv (`.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/anki-gitify`).
