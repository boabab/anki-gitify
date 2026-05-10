# anki-gitify — design

A CLI that converts an Anki deck (with subdecks) into a git-versionable directory of plain-text files, and back into an importable `.apkg`. The point: put your decks on GitHub, edit them in a real editor, diff changes, collaborate via PRs — without an Anki plugin, and without losing card structure or templates.

This document is the **living spec**. If you change the on-disk format, update this file in the same commit and bump `SCHEMA_VERSION` in [`src/anki_gitify/schema.py`](../src/anki_gitify/schema.py).

---

## What's preserved vs dropped (v1)

### Preserved
- Notes (fields, tags, GUIDs, **per-note home deck path**)
- Note types: name, kind, fields, sort field, CSS, LaTeX pre/post, all card templates (front/back HTML, optional browser format)
- Deck hierarchy + descriptions
- Filtered-deck definitions: name, search/limit/order terms, resched flag, custom delays
- Media files referenced from any note field or template HTML

### Dropped (intentional)
- Scheduling state on cards: `type`, `queue`, `due`, `ivl`, `factor`, `reps`, `lapses`, `left`, `odue`, `odid`, `flags`
- Review log (`revlog`)
- Deletion tracker (`graves`)

A future v2 may opt in scheduling state via `--with-scheduling`.

---

## Anki architecture context

- Collection: `~/Library/Application Support/Anki2/<profile>/collection.anki2` (SQLite). On Linux it's `~/.local/share/Anki2/`; on Windows `%APPDATA%/Anki2/`.
- Stack: Anki desktop GUI (`aqt`) → `anki` Python module (PyPI) → Rust `rslib` via `rsbridge` → SQLite.
- The `anki` PyPI package is importable standalone (no `aqt`), so we don't need Anki running to read/write collections.
- **Reads** go through the Python API (`anki.collection.Collection`); direct SQLite reads are also fine.
- **Writes** to a live collection are dangerous (bypass undo, sync state, schema-mod timestamps). We avoid them: the import path produces a `.apkg` via `genanki`, which the user imports manually with File → Import.
- Modern Anki (v15+) uses normalized tables (`notetypes`, `fields`, `templates`, `decks`, `deck_config`) backed by protobuf BLOBs, but `col.models.get(mid)` and `col.decks.get(did)` still return legacy dicts that expose everything we need (`flds`, `tmpls`, `css`, `dyn`, `terms`). We use those — easier than decoding protobuf.

---

## Schema entities and how each is handled

| Entity | Source | What we keep | What we drop |
|---|---|---|---|
| `notes` | `notes` table | `guid`, `tags`, fields, **home deck path** (per-note) | `id`, `mid`, `mod`, `usn`, `csum` (regenerated on import) |
| `cards` | `cards` table | per-card overrides only when a single note's cards have **divergent** home decks (rare); otherwise nothing | scheduling: `type`, `queue`, `due`, `ivl`, `factor`, `reps`, `lapses`, `left`, `odue`, `odid`, `flags` |
| `notetypes` | `col.models.get()` | name, kind (normal/cloze), fields, sort field, CSS, LaTeX pre/post, all card templates | `id` (regenerated stably from name) |
| `templates` | nested in notetype | `name`, `qfmt`, `afmt`, `bqfmt`, `bafmt` (last two only if non-default) | — |
| `decks` (normal) | `col.decks.get()` | name (full path), description | scheduling config |
| `decks` (filtered) | same, `dyn=1` | name, `terms` (search + limit + order), `resched`, `delays` | currently-selected card list (re-runs the search on rebuild) |
| `revlog` | — | nothing | everything |
| `graves` | — | nothing | everything |

**On the term "modes per note":** these are the **card templates** of the note's notetype. A bidirectional notetype has 2 templates → each note generates 2 cards (`cards.ord` 0 and 1). Cloze notetypes generate one card per cloze deletion in the field. Both are derived from `(notetype, field content)` at render time — we just preserve the templates and field text.

---

## On-disk format

One gitified deck = one directory:

```
<gitified-deck>/
  gitify.yml                           # schema_version, tool_version, source profile, exported_at, anki_version, root deck name, counts
  deck.yml                             # this (root) deck's name (last component), description
  decks/                               # subdecks, recursive
    <SubdeckSlug>/
      deck.yml
      decks/ ...
  notetypes/
    <notetype-slug>/
      meta.yml                         # name, kind, sort_field_index, latex_pre, latex_post
      fields.yml                       # ordered list: name, font, size, sticky, rtl, plain_text, description
      style.css                        # the notetype CSS
      templates/
        00-<template-slug>/
          meta.yml                     # name (canonical), ordinal
          front.html                   # qfmt
          back.html                    # afmt
          browser_front.html           # bqfmt — only if it differs from qfmt
          browser_back.html            # bafmt — only if it differs from afmt
        01-<template-slug>/ ...
  notes/
    <notetype-slug>.csv                # columns: guid, deck_path, tags, <field1>, <field2>, ...
                                       # csv.QUOTE_ALL, UTF-8 no-BOM, \n line endings, sorted by (deck_path, guid)
  cards.csv                            # OPTIONAL — only when a single note's cards have DIVERGENT home decks
                                       # columns: note_guid, ord, deck_path  (only diverging ord rows)
                                       # v1 import: error unless `--ignore-card-overrides` passed (lossy fallback)
  filtered_decks.yml                   # structured spec (canonical, machine-readable)
  FILTERED_DECKS.md                    # human-readable view auto-generated from filtered_decks.yml
  media/
    <original-filename>                # NFC-normalized; flat namespace per Anki convention
```

**Determinism is a hard requirement.** Re-exporting the same collection must produce a byte-identical tree (modulo `gitify.yml`'s `exported_at`). That means: sorted directory iteration, CSV rows sorted by `(deck_path, guid)`, `yaml.safe_dump(..., sort_keys=True)`, LF line endings, and `FILTERED_DECKS.md` rendered with the same template every time.

### Examples

`notetypes/bidirectional/meta.yml`:
```yaml
name: Bidirectional
kind: normal
sort_field_index: 0
latex_pre: ""
latex_post: ""
```

`notetypes/bidirectional/templates/00-front-back/front.html`:
```html
{{Front}}
```

`notetypes/bidirectional/templates/00-front-back/back.html`:
```html
{{FrontSide}}<hr id=answer>{{Back}}
```

`notes/bidirectional.csv`:
```csv
"guid","deck_path","tags","Front","Back"
"abc123","Japanese::Vocab::Kanji","kanji n5","日","sun, day"
"def456","Japanese::Vocab::Kanji","kanji n5","月","moon, month"
"ghi789","Japanese::Sentences","example","これは日本語です","This is Japanese"
```

`deck_path` is the **home deck** of the note's cards (computed as `odid if odid > 0 else did` per card; if cards diverge, see `cards.csv`). Storing it explicitly per row means a notetype can be shared across multiple decks and the placement is unambiguous on import — no inference from directory layout.

`cards.csv` (only emitted when divergent):
```csv
"note_guid","ord","deck_path"
"xyz999","1","Japanese::Sentences::Audio"
```

Only rows that diverge from the note's `deck_path` in `notes/<notetype>.csv` appear here.

`filtered_decks.yml` mirrors Anki's internal `decks.terms` structure. Top-level object with `schema_version` so the file is self-describing:
```yaml
schema_version: 1
filtered_decks:
  - name: "Japanese::Cram::Due+Lapses"
    resched: true
    delays: null
    terms:
      - search: "deck:Japanese (is:due OR rated:7:1)"
        limit: 100
        order: 5
  - name: "Japanese::Cram::Recent"
    resched: false
    delays: null
    terms:
      - search: "deck:Japanese added:14"
        limit: 50
        order: 0
```

The `order` integer mirrors Anki's `FilteredDeckTerms.order` enum (0=oldest, 1=newest, 2=lapses-first, 3=shortest-interval, 4=longest-interval, 5=most-retrievable, etc.). Stored as int rather than string for stability across Anki versions; the human-readable name lives in [`schema.py:ORDER_NAMES`](../src/anki_gitify/schema.py).

`FILTERED_DECKS.md` is auto-generated from `filtered_decks.yml` at export time, also committed to git so it renders nicely on GitHub. The renderer is [`export/filtered.py:render_filtered_md`](../src/anki_gitify/export/filtered.py).

### Slug rules

- Lowercase, dash-separated, ASCII fallback for non-ASCII (NFKD + strip).
- On collision: append `-2`, `-3`, etc.
- Canonical name preserved in `meta.yml`'s `name:` — slug is just the directory.

---

## Export algorithm

Entry: `anki-gitify export <deck-name> <out-dir>` → [`export/exporter.py:export`](../src/anki_gitify/export/exporter.py).

1. **Resolve profile + collection path** ([`profile.py`](../src/anki_gitify/profile.py)). If `collection.anki2` is locked, surface "Close Anki and retry."
2. **Open**: `from anki.collection import Collection; col = Collection(path)`.
3. **Resolve target deck**: `did = col.decks.id_for_name(deck_name)`. If `None`, suggest near matches. **Reject if the root is a filtered deck** (`col.decks.get(did)['dyn'] == 1`) — filtered decks have no notes of their own, so exporting one as a root has no sensible meaning in v1.
4. **Walk subdeck tree** ([`export/decks.py:build_tree`](../src/anki_gitify/export/decks.py)). Split into:
   - `normal_scope` = ids of normal decks (root + normal subdecks) — the deck-tree skeleton.
   - `filtered_scope` = ids of filtered decks under the root — these go to `filtered_decks.yml`, not the deck tree.
5. **Collect cards/notes by HOME deck, not current location.** A card's home is `odid if odid > 0 else did` (when `odid > 0` the card has been temporarily pulled into a filtered deck and `odid` records where it belongs):
   ```sql
   SELECT id, nid, did, ord, odid FROM cards
   WHERE (CASE WHEN odid > 0 THEN odid ELSE did END) IN (:normal_scope)
   ```
   This includes cards currently inside filtered decks under our root (their home is in scope), and excludes cards a filtered deck pulls from outside our scope.
6. **Collect referenced notetypes**: `SELECT DISTINCT mid FROM notes WHERE id IN (...)`. Load via `col.models.get(mid)`.
7. **Emit `notetypes/`** ([`export/notetypes.py`](../src/anki_gitify/export/notetypes.py)).
8. **Compute home-deck-per-note** ([`export/cards.py:compute_placements`](../src/anki_gitify/export/cards.py)). Pick the deck with the most cards as the note's `deck_path`; record divergent ords for `cards.csv`.
9. **Emit `notes/`** ([`export/notes.py`](../src/anki_gitify/export/notes.py)). Header: `["guid", "deck_path", "tags"] + field_names`. Rows sorted by `(deck_path, guid)`.
10. **Emit deck tree** ([`export/decks.py:emit_deck_tree`](../src/anki_gitify/export/decks.py)). Walk `normal_scope` only. Each `deck.yml` carries the **last path component** as `name` plus `description`.
11. **Emit `filtered_decks.yml` + `FILTERED_DECKS.md`** ([`export/filtered.py`](../src/anki_gitify/export/filtered.py)).
12. **Emit `cards.csv`** ([`export/notes.py:emit_cards_csv`](../src/anki_gitify/export/notes.py)) — only diverging rows.
13. **Emit `media/`** ([`export/media.py`](../src/anki_gitify/export/media.py)). Scan field HTML and template HTML for `<img src=>`, `<source src=>`, `[sound:…]`. Copy from `<profile>/collection.media/` with NFC-normalized names. Don't sweep unreferenced media.
14. **Emit `gitify.yml`** with counts and source metadata.
15. **Close** the collection.

---

## Import algorithm

Entry: `anki-gitify import <in-dir> <out.apkg> [--ignore-card-overrides]` → [`importer/importer.py:import_`](../src/anki_gitify/importer/importer.py).

1. **Load and validate `gitify.yml`** — refuse unknown major schema versions.
2. **Refuse early on `cards.csv`** unless `--ignore-card-overrides` was passed. The v1 importer (genanki-based) cannot reproduce per-card deck placement and would silently lose this data. The flag makes the loss explicit.
3. **Walk deck tree** → set of full deck paths (from `decks/` *and* the unique `deck_path` values in every `notes/*.csv`). Build `genanki.Deck(deck_id=fingerprint.deck_id_for(path), name=path)` for each.
4. **Load notetypes** ([`importer/loader.py`](../src/anki_gitify/importer/loader.py) + [`importer/genanki_build.py`](../src/anki_gitify/importer/genanki_build.py)). Build `genanki.Model` with `model_id=fingerprint.model_id_for(name)`.
5. **Load notes**. For each row: look up the model, look up the target deck by `deck_path`, build `genanki.Note(..., guid=guid)`. Pass `guid` explicitly so re-imports update existing notes rather than duplicating.
6. **Build the package**:
   ```python
   pkg = genanki.Package(list_of_decks)
   pkg.media_files = [str(p) for p in (in_dir / "media").iterdir()]
   pkg.write_to_file(out_apkg)
   ```
7. **Filtered decks**: not written into the `.apkg` (genanki has no filtered-deck primitive). Print a stdout summary listing each filtered deck name + search; the canonical files live at `filtered_decks.yml` and `FILTERED_DECKS.md` already.
8. **Print** the destination `.apkg` path. User imports via Anki's File → Import.

---

## Filtered deck handling

### Export side
- Filtered decks under the root are detected by `dyn=1` in `col.decks.get(did)` and routed to `filtered_decks.yml`, not the `decks/` tree.
- A card's **home deck** is `odid if odid > 0 else did`. We always record the home, never the filtered-deck id, when placing a note. Re-exporting before vs after running a filtered deck produces an identical tree (modulo `gitify.yml`'s timestamp).
- A filtered deck pulls cards based on its search query. If that query matches cards whose home is **outside** our export scope, those cards are excluded — they belong to a different export. The filter string is preserved verbatim regardless.

### Import side
The `.apkg` contains only normal decks. After File → Import:
- Cards land in their home decks.
- Filtered decks are recreated separately. Two artifacts already live in the gitified directory:
  - `filtered_decks.yml` — canonical machine-readable spec (consumed by v2's `apply-filtered`).
  - `FILTERED_DECKS.md` — derived human-readable view.

The `import` command prints a summary pointing at those files and listing the searches inline.

### v2: `apply-filtered` (shipped)
Subcommand `anki-gitify apply-filtered <gitified-dir> [--profile NAME] [--collection PATH] [--dry-run]` reads `filtered_decks.yml` and writes the filtered decks into a live collection programmatically. Implementation lives in [`importer/apply_filtered.py`](../src/anki_gitify/importer/apply_filtered.py).

Each entry is classified into one of three buckets:
- **created** — name does not exist in the target collection; the filtered deck is created via `col.decks.new_filtered(name)`, then `terms`/`resched`/`delays` are written and the deck saved.
- **skipped** — a filtered deck (`dyn=1`) with the same name already exists. Left untouched (idempotent).
- **conflict** — a *normal* deck (`dyn=0`) with the same name exists. Anki's `new_filtered` would silently return the existing deck without converting it, so we refuse and report instead. The CLI exits with code 2 if any conflicts are reported.

`--dry-run` opens the collection read-only-ish (no `save` calls) and prints the same classification without writing.

Only deck metadata is touched — never notes/cards/scheduling — so it's much lower-risk than a full live-collection write. The user must close Anki first (we open the collection through `open_collection` which surfaces a clear error if the file is locked).

### Cards currently inside filtered decks at re-import
Anki's `.apkg` import dedups by `notes.guid`:
- The note's fields, tags, and home deck are updated.
- The card's current `did` (the filtered deck) and the temporary scheduling fields (`odue`, `due`) are not touched.
- This usually self-resolves on the next filtered-deck empty/rebuild. For larger structural changes (renaming a notetype, restructuring fields), recommend emptying filtered decks before importing.

### v2 `--lossless` mode (deferred)
Build a fresh `Collection` in a temp dir, replay decks/notetypes/notes via the official write API, then call `col.export_anki_package(...)`. Recreates filtered decks in the .apkg directly (no manual step) and opens the door to scheduling export. Strictly more code and tighter `anki`-version coupling, so it's not v1.

---

## Stable identity across round-trips

- **Notes** are deduped by `notes.guid`. Preserved verbatim in the CSV. Re-imports update existing notes; scheduling on the user's collection is preserved because the note isn't deleted-and-recreated.
- **Notetypes**: genanki uses arbitrary integer model IDs. We derive a stable ID from `sha1(name)`:
  ```python
  def model_id_for(name: str) -> int:
      return int.from_bytes(hashlib.sha1(name.encode("utf-8")).digest()[:8], "big") & ((1 << 63) - 1)
  ```
  63-bit positive int → vanishingly unlikely to collide with epoch-millisecond IDs Anki normally generates (~41 bits). See [`fingerprint.py`](../src/anki_gitify/fingerprint.py).
- **Decks** are deduped by name. Stable IDs not strictly required; we still derive them via `deck_id_for(full_path)` for predictability.
- **Caveat**: changing notetype structure (adding/removing/reordering fields, changing template count) triggers Anki's "schema modification" rules and **invalidates scheduling on existing cards**. Editing field *content*, CSS, or template HTML is safe.

---

## Media handling

- **Export**: scan all field HTML and template HTML with regexes from [`media_refs.py`](../src/anki_gitify/media_refs.py) (`<img src=>`, `<source src=>`, `[sound:…]`). Copy from `<profile>/collection.media/` to `<out-dir>/media/` with NFC-normalized names. Skip data URIs and remote URLs. Don't sweep unreferenced media.
- **Import**: pass file paths to `genanki.Package.media_files`. Filenames must match HTML references — never rename.
- **macOS NFC/NFD**: macOS APFS commonly stores filenames as NFD; Anki uses NFC. The exporter tries both spellings when copying.
- For large audio/video, ship a commented-out `.gitattributes` LFS template the user can opt into.

---

## Why not just CrowdAnki / genanki?

- **CrowdAnki** is the closest existing project. It's an Anki plugin (not a CLI), so it requires the desktop app to be open. Its JSON format embeds notetypes per export but stores notes as flat JSON arrays — less git-diff-friendly than per-notetype CSVs with one row per note. Our format also wraps filtered decks in a strict schema for the v2 `apply-filtered` path; CrowdAnki doesn't model that workflow.
- **genanki** alone produces `.apkg` files but cannot read existing decks. It's the right primitive for the import side (we use it) but not a full solution.
- **AnkiPandas** reads collections into DataFrames — useful as a reference but adds a dep we don't need on top of `anki.collection.Collection`.

---

## Open caveats

- **Python version**: `anki` PyPI lags the newest Python. Project requires Python 3.11–3.13 (3.13 currently works; 3.14 wheels not yet published).
- **Schema modifications invalidate scheduling**: editing fields/templates and re-importing triggers Anki's schema-mod path and resets card scheduling on existing cards. README warns about this.
- **Per-card deck overrides** (rare): `cards.csv` round-trips losslessly on the export side. v1 import refuses without `--ignore-card-overrides`; with the flag, all cards of an affected note collapse into the note's primary `deck_path`. v2 lossless mode will respect overrides.
- **Filtered deck as export root rejected in v1**: filtered decks have no notes of their own. `export` errors out and points at home decks instead.
- **Filtered decks need one manual recreation step** post-import — or run `anki-gitify apply-filtered` (v2, shipped) to write them directly into the live collection.
- **Filtered-deck search referencing decks outside the export scope**: those cards are correctly excluded from the export. The filter string is preserved verbatim and may match nothing when re-imported into a collection that lacks the referenced decks — that's expected, not a bug.
- **Schema versioning in `gitify.yml`** is critical from day 1 — a v2 that adds e.g. scheduling export must still consume v1 repos.

---

## Determinism rules (must hold)

- Sorted directory iteration in every emitter.
- CSV rows sorted by `(deck_path, guid)`; `csv.QUOTE_ALL`; LF newlines; UTF-8 no-BOM.
- `yaml.safe_dump(..., sort_keys=True)`; LF newlines.
- `FILTERED_DECKS.md` rendered by [`render_filtered_md`](../src/anki_gitify/export/filtered.py) — same template every time.
- HTML/CSS files written verbatim with LF newlines (no normalization).
- Slugs assigned in name-sorted order so collisions are stable across runs.

The round-trip test in [`tests/test_roundtrip.py`](../tests/test_roundtrip.py) is the executable spec: export → import → re-export → byte-equal diff (modulo `gitify.yml.exported_at`).

---

## Conventions for changes

- Bump `SCHEMA_VERSION` in [`schema.py`](../src/anki_gitify/schema.py) for any backward-incompatible on-disk format change, and update this document in the same commit.
- The pydantic models in `schema.py` are the field-level validation contract. This document shows the shape; `schema.py` enforces it.
- Tests in [`tests/`](../tests) pin behavior. The round-trip test catches drift; CLI tests catch surface regressions.
