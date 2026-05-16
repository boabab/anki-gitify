# `anki_gitify.api` — public Python API

This file documents the **stable, supported surface** for embedding
`anki-gitify` in another tool. Anything that imports from `anki_gitify.api`
is covered by the SemVer rules below; anything that imports from elsewhere
inside the package is using internals and is on its own across upgrades.

## What's stable

```python
from anki_gitify.api import (
    API_VERSION,
    # build a .apkg from a gitified directory
    import_, ImportReport, CardOverrideError,
    # write filtered-deck definitions into a live collection
    apply_filtered, ApplyFilteredReport,
    # validate a gitified directory (no Anki needed)
    verify, VerifyReport,
    # parse a gitified directory into in-memory dataclasses
    load, LoadedRepo,
    # locate the user's Anki install
    list_profiles, resolve_profile_paths, default_anki_base, ProfilePaths,
    # semantic diff between two states of a gitified deck
    run_diff, RevInput, DiffEnvelope, DIFF_SCHEMA_VERSION,
)
```

`API_VERSION` is a `(major, minor, patch)` tuple. Bump it whenever the surface
changes — even on minor/patch — so consumers can detect mismatches at
runtime.

## SemVer rules

* **Patch** (`X.Y.Z+1`): bug fixes only. No surface change.
* **Minor** (`X.Y+1.0`): additive changes — new names, new optional kwargs,
  new fields on returned dataclasses. Existing call patterns keep working.
* **Major** (`X+1.0.0`): removals, renames, or any change that breaks a
  documented call pattern.

The `tests/test_api_surface.py` test enforces the additive part: it fails if a
documented name or dataclass field disappears, but passes silently when new
ones are added.

## Stability guarantees in detail

### Function signatures

The required parameters listed below are guaranteed to stay. New optional
keyword arguments may be added in minor releases — write your code as if you
might receive new fields on returned dataclasses too.

```python
import_(in_dir: Path, out_apkg: Path,
        *, ignore_card_overrides: bool = False) -> tuple[ImportReport, LoadedRepo]

apply_filtered(in_dir: Path, collection_path: Path,
               *, dry_run: bool = False) -> ApplyFilteredReport

verify(in_dir: Path) -> VerifyReport

load(in_dir: Path) -> LoadedRepo

list_profiles(base: Path) -> list[str]

resolve_profile_paths(profile: str | None = None,
                      base: Path | None = None,
                      collection_override: Path | None = None) -> ProfilePaths

default_anki_base() -> Path

run_diff(rev_a: RevInput, rev_b: RevInput,
         *, repo_path: Path | None = None,
         cwd: Path | None = None,
         output_format: Literal["json", "text"] = "text",
         color: bool = False, abbrev: bool = False,
         compact: bool = False) -> tuple[DiffEnvelope, str]
```

### Diff envelope

`DiffEnvelope` is a pydantic model. The canonical contract is its JSON
serialization, not the Python attributes: serialize with `.model_dump(mode="json")`
and consume the result as a dict. `DIFF_SCHEMA_VERSION` is the version
integer embedded in that JSON (currently `1`). See
[docs/DESIGN.md](DESIGN.md) §"Semantic diff" for the JSON schema.

`RevInput` selects what to diff:

```python
RevInput.working_tree()        # the current state on disk
RevInput.from_ref("HEAD")      # any git ref or sha
RevInput.from_ref("v0.2.0")
```

Typical call: `run_diff(RevInput.from_ref("HEAD"), RevInput.working_tree(), repo_path=Path("/path/to/gitified"))`.

### Returned dataclasses

Treat these as **append-only**. Read attributes by name, don't unpack
positionally; don't rely on the ordering of `dataclasses.fields()`.

```python
@dataclass
class ImportReport:
    out_apkg: Path
    notes: int
    media_files: int
    filtered_decks: int
    card_overrides_ignored: int

@dataclass
class ApplyFilteredReport:
    collection: Path
    created: list[str]
    skipped: list[str]
    conflicts: list[str]
    dry_run: bool
    # `total` is a derived @property, not a field — count via len() on the lists.

@dataclass
class VerifyReport:
    in_dir: Path
    ok: bool
    errors: list[str]
    notetypes: int
    notes: int
    media: int
    filtered_decks: int

@dataclass
class LoadedRepo:
    in_dir: Path
    gitify: dict
    notetypes: list[LoadedNoteType]
    notes: list[LoadedNote]
    card_overrides: list[LoadedCardOverride]
    deck_tree: LoadedDeckTree
    filtered: FilteredDecksFile
    media_files: list[Path]

@dataclass(frozen=True)
class ProfilePaths:
    base: Path
    profile: str
    collection: Path
    media_dir: Path
```

### Exceptions

Catch by class, not message:

* `CardOverrideError` — `import_` was called against a gitified directory
  that contains a non-empty `cards.csv` and `ignore_card_overrides=False`.
* `RuntimeError` (any `RuntimeError` whose message contains the substring
  `"locked"`) — Anki is open and the collection database is locked.
  Surface this to the user as "close Anki and try again." Future versions
  may use a more specific subclass; the substring contract is the
  forward-compatible thing to match on.
* `ValueError` / `FileNotFoundError` — invalid input, missing files,
  unsupported schema versions. Always include a human-readable message.

### What is **not** stable

Anything not in `anki_gitify.api`. In particular, `anki_gitify.importer.*`,
`anki_gitify.export.*`, `anki_gitify.collection_io`, `anki_gitify.schema`,
and `anki_gitify._yaml` are internals and may move, rename, or change
signatures between minor releases. If you find yourself reaching past
`anki_gitify.api` for something, open an issue describing the use case so we
can promote the right thing into the public surface.

## Migration guide for major bumps

When a major bump happens, the changelog will list:

1. Names removed from the surface.
2. Dataclass fields removed.
3. Renames (with the old → new mapping).
4. Behavioral changes to documented call patterns.

Everything not listed continues to work. The expectation is that consumers
read the changelog, update their code, and pin to the new major.
