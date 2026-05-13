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

## Semantic diff (`anki-gitify diff`)

A third pipeline alongside export/import: compare two states of a gitified directory and emit a structured report of what changed at the deck-semantic layer (notes, notetypes, filtered decks, deck tree, media). It exists to power:

1. **Pre-push audit** — `anki-gitify diff` with no args compares `HEAD` against the working tree, so the user can verify that what they're about to push matches what they actually changed in Anki.
2. **History browser** — `anki-gitify diff REV_A REV_B` compares two arbitrary refs/shas, so a UI can render PR-style "what changed between these two snapshots" views over the gitified repo's git history.

Both use cases share one JSON shape. The CLI also emits a polished terminal-text rendering for inspection without firing up the UI.

### CLI surface

```
anki-gitify diff [REV_A] [REV_B] [--format json|text] [--exit-code] [--abbrev] [--color WHEN] [--repo PATH] [--compact] [--output PATH]
```

- **Positional refs** (both optional):
  - 0 args → `HEAD` vs working tree (the pre-push audit).
  - 1 arg → `REV_A` vs working tree.
  - 2 args → `REV_A` vs `REV_B` (history browsing).
- **`--format json|text`** — default `text` (humans first). JSON is the stable contract consumed by the UI.
- **`--exit-code`** — opt-in: exit 1 if any change detected (pre-push hook usage). Default exit 0 regardless, matching `git diff`.
- **`--abbrev`** — opt-in truncation for very long template / CSS / field content in text output. Default shows full content.
- **`--color always|auto|never`** — ANSI color. Default auto: on for TTY, off when piped.
- **`--repo PATH`** — override the gitified-repo location. Default walks up from CWD looking for `gitify.yml` (mirrors how `git` locates `.git`). Errors with a clear message if none found.
- **`--compact`** — emit compact JSON instead of pretty-printed. Default pretty (multi-line, two-space indent).
- **`--output PATH`** — write to file instead of stdout. Stdout is the default.

Reading non-working-tree revs: `git worktree add --detach <tmpdir> <ref>` into a tempdir, parse it with the existing loader, then `git worktree remove`. Zero code duplication for the read side — same loader as `import` and `verify`. The working tree is read directly via the loader without any git mediation.

### What "semantic diff" means

The git index can show `notes/bidirectional.csv` changed by 4 lines. Semantic diff says: "3 notes had the `covered` tag added; 1 note's `pīnyīn` field changed from `ku3` to `kǔ`." The diff is computed entity-by-entity at the level of the pydantic models in [`schema.py`](../src/anki_gitify/schema.py) — not at the level of bytes in CSV / YAML / HTML files.

What's diffed:

- **Notes** — keyed by `notes.guid`. Detects: tag add/remove, field edits, deck moves, notetype changes, card-override changes.
- **Notetypes** — keyed by canonical `name`. Detects: field add/remove and field-order changes; per-template `qfmt`/`afmt`/`bqfmt`/`bafmt` edits; `css`, `latex_pre`, `latex_post` edits; `sort_field_index` changes.
- **Filtered decks** — keyed by `name`. Detects: changes in `search`, `limit`, `order`, `resched`, `delays`.
- **Deck tree** — added/removed deck paths only (no internal state per deck beyond its path).
- **Media** — added/removed by filename, with size + content hash for each entry.

What's NOT diffed:

- `gitify.yml.exported_at` and `gitify.yml.tool_version` (metadata noise from re-exports).
- `notes` table ordering within a CSV (rows are keyed by guid; row order is determined by sort rules, not content).
- File-level whitespace inside YAML/CSV that doesn't change the parsed pydantic model.

Notetype renames are **not** detected heuristically in v1: a renamed notetype appears as the old name in `removed` and the new name in `added`. Same philosophy for renamed fields within a notetype: remove-old + add-new.

### JSON contract

The JSON output has its own `schema_version` independent of the gitified-format `SCHEMA_VERSION`. Adding a new key or a new warning `kind` is non-breaking and does not bump it. Removing/renaming a key, changing a value's type, or changing the semantics of an existing `kind` is breaking and bumps it. UIs pin a min/max they support.

#### Envelope

```jsonc
{
  "schema_version": 1,
  "tool_version": "0.3.0",
  "generated_at": "2026-05-13T10:31:00Z",
  "source": {
    "repo_path": "/home/user/anki-decks/japanese",
    "root_deck": "Japanese"
  },
  "rev_a": {
    "kind": "ref",
    "ref": "HEAD",
    "sha": "abc123def456...",
    "commit_timestamp": "2026-05-12T18:45:22Z",
    "commit_subject": "Add HSK1 vocab"
  },
  "rev_b": {
    "kind": "working_tree"
  },
  "summary": {
    "notes":          {"added": 0, "removed": 0, "changed": 3},
    "notetypes":      {"added": 0, "removed": 0, "changed": 1},
    "filtered_decks": {"added": 0, "removed": 0, "changed": 0},
    "decks":          {"added": 0, "removed": 0},
    "media":          {"added": 0, "removed": 0}
  },
  "warnings": [],
  "notes":          { "added": [], "removed": [], "changed": [ /* ... */ ] },
  "notetypes":      { "added": [], "removed": [], "changed": [ /* ... */ ] },
  "filtered_decks": { "added": [], "removed": [], "changed": [] },
  "deck_tree":      { "added": [], "removed": [] },
  "media":          { "added": [], "removed": [] }
}
```

`rev_a` and `rev_b` are discriminated unions on `kind`:
- `{"kind": "ref", "ref": <str>, "sha": <str>, "commit_timestamp": <iso>, "commit_subject": <str>}`
- `{"kind": "working_tree"}`

Every top-level entity section uses **by-status grouping** — `{added, removed, changed}` — never a flat array.

Empty-diff output: a full envelope with all-zero summary, empty entity sections, empty warnings. Text output adds one line: `no semantic changes between <rev_a> and <rev_b>`.

#### Note record

A "full note snapshot" is comprehensive enough that a UI can render a note card without joining other sections:

```jsonc
{
  "guid": "abc123",
  "label": "苦  /  kǔ  /  bitter",
  "deck_path": "Japanese::Vocab",
  "notetype_name": "Hanzi-Pinyin-English",
  "notetype_slug": "hanzi-pinyin-english",
  "tags": ["hsk1", "vocab"],
  "fields": [
    {"name": "Hànzì",   "value": "苦"},
    {"name": "pīnyīn",  "value": "kǔ"},
    {"name": "English", "value": "bitter"}
  ],
  "card_overrides": [
    {"ord": 0, "deck_path": "Japanese::Vocab::Suspended"}
  ]
}
```

`label` is the sort-field value with HTML tags stripped, joined with the next 1–2 fields by `  /  `, capped at ~80 chars. Provided so list views have a quick anchor without rendering all fields. `fields` is an **ordered list of `{name, value}` objects** — array position preserves notetype field order, and the object shape leaves room to add field metadata later without breaking consumers. `card_overrides` is included inline in the note record (not a separate top-level section) so the card belongs to the note in JSON the way it does in Anki.

#### Notetype record

A "full notetype snapshot" is a full structural dump:

```jsonc
{
  "name": "Hanzi-Pinyin-English",
  "slug": "hanzi-pinyin-english",
  "kind": "standard",
  "sort_field_index": 0,
  "fields": [
    {"name": "Hànzì",   "font": "Arial", "size": 20},
    {"name": "pīnyīn",  "font": "Arial", "size": 18},
    {"name": "English", "font": "Arial", "size": 18}
  ],
  "templates": [
    {
      "name": "Card 1",
      "qfmt":  "<div class='hanzi'>{{Hànzì}}</div>",
      "afmt":  "{{FrontSide}}<hr>{{pīnyīn}}<br>{{English}}",
      "bqfmt": "",
      "bafmt": ""
    }
  ],
  "css":        ".card { font-family: serif; ... }",
  "latex_pre":  "\\documentclass[12pt]{article}\n...",
  "latex_post": "\\end{document}"
}
```

Templates and CSS are included as full strings in both `before` and `after` snapshots. Their `changes` block additionally carries a precomputed `unified_diff` string (see below).

#### Smaller entity records

```jsonc
"deck_tree": {
  "added":   ["Japanese::HSK1"],
  "removed": []
},
"media": {
  "added":   [{"filename": "hanzi_ku.mp3",  "size": 18403, "content_hash": "sha256:abc..."}],
  "removed": [{"filename": "hanzi_old.mp3", "size": 17500, "content_hash": "sha256:def..."}]
},
"filtered_decks": {
  "added":   [{ /* full FilteredDeck pydantic dump */ }],
  "removed": [],
  "changed": [{
    "before":  { /* full FilteredDeck dump */ },
    "after":   { /* full FilteredDeck dump */ },
    "changes": {
      "search_changed":     {"before": "deck:Vocab is:due", "after": "deck:Vocab is:learn"},
      "limit_changed":      {"before": 100, "after": 200},
      "order_changed":      null,
      "resched_changed":    null,
      "delays_changed":     null
    }
  }]
}
```

Media `content_hash` is `sha256:<hex>` over the file bytes. It lets a UI detect renames (same hash, new name) without us doing rename detection ourselves.

#### Changed-entity shape (`{before, after, changes}`)

Every entry in a `changed` array carries three keys:

- `before` — the full snapshot at `rev_a`.
- `after` — the full snapshot at `rev_b`.
- `changes` — a precomputed delta block with **maximal keys** (every potential delta key is always present; the value is empty array / `null` if nothing changed in that dimension). UIs don't need to handle missing keys.

For **note** entries:

```jsonc
"changes": {
  "tags_added":         ["covered"],
  "tags_removed":       [],
  "deck_moved":         null,
  "notetype_changed":   null,
  "fields_changed": [
    {
      "name":         "pīnyīn",
      "before":       "ku3",
      "after":        "kǔ",
      "unified_diff": "@@ -1 +1 @@\n-ku3\n+kǔ\n"
    }
  ],
  "card_overrides_changed": []
}
```

- `deck_moved`: `null` or `{"before": "<path>", "after": "<path>"}`.
- `notetype_changed`: `null` or `{"before": "<name>", "after": "<name>"}` (rare — happens when the user runs Anki's "Change Note Type").
- `fields_changed`: array of `{name, before, after, unified_diff}` entries — one per field that changed value. The `unified_diff` is always included, even for single-line edits, for UI consistency; UIs are free to ignore it on short content.
- `card_overrides_changed`: array of `{ord, before: {deck_path}|null, after: {deck_path}|null}` entries — `null` either side means the override was added or removed.

For **notetype** entries:

```jsonc
"changes": {
  "sort_field_index_changed": null,
  "fields_changed": [
    {"status": "added",   "name": "English", "index": 2, "font": "Arial",          "size": 18},
    {"status": "removed", "name": "Eng",     "index": 2, "font": "Arial",          "size": 18},
    {"status": "changed", "name": "Hànzì",
      "before": {"font": "Arial",          "size": 20},
      "after":  {"font": "Noto Sans CJK",  "size": 24}}
  ],
  "field_order_changed": null,
  "templates_changed": [
    {
      "name":  "Card 1",
      "qfmt":  null,
      "afmt":  {"before": "...old html...", "after": "...new html...", "unified_diff": "@@ ... @@\n-old\n+new\n"},
      "bqfmt": null,
      "bafmt": null
    }
  ],
  "css_changed":        null,
  "latex_pre_changed":  null,
  "latex_post_changed": null
}
```

- `fields_changed` records each field added/removed/changed by name. A field rename appears as add-new + remove-old (no rename detection in v1).
- `field_order_changed`: `null` or `{"before": ["...", ...], "after": ["...", ...]}` — emitted when only the order shifted (the field set is unchanged but the indices moved).
- `templates_changed`: array of `{name, qfmt, afmt, bqfmt, bafmt}` where each of the four format slots is either `null` (unchanged) or `{before, after, unified_diff}` (changed). Includes the full HTML strings in both `before` and `after` — the UI can render side-by-side, syntax-highlight, or just show the diff hunk depending on context.
- `css_changed`, `latex_pre_changed`, `latex_post_changed`: `null` or `{before, after, unified_diff}`.

#### Warnings

```jsonc
"warnings": [
  {
    "kind":    "schema_mismatch",
    "message": "rev_a is SCHEMA_VERSION=1, rev_b is SCHEMA_VERSION=2",
    "details": {"rev_a_version": 1, "rev_b_version": 2}
  },
  {
    "kind":    "unknown_notetype_reference",
    "message": "3 notes in rev_b reference notetype 'Hanzi-Old' which is not present in rev_b",
    "details": {"notetype_name": "Hanzi-Old", "note_guids": ["abc", "def", "ghi"]}
  }
]
```

`kind` is from a closed set, documented here. Adding a new `kind` is non-breaking. Defined kinds:

- `schema_mismatch` — `rev_a` and `rev_b` declare different `SCHEMA_VERSION` in their `gitify.yml`. Best-effort comparison proceeds; details carry both versions.
- `missing_gitify_yml` — one of the revs doesn't contain a parseable `gitify.yml`. Details: `{rev: "a"|"b"}`.
- `unknown_notetype_reference` — a note references a notetype not present in the same rev. Details: `{notetype_name, note_guids: [...], rev: "a"|"b"}`.
- `undecodable_file` — a file existed at a known path but failed to parse. Details: `{rev: "a"|"b", path: "...", error: "..."}`.
- `working_tree_dirty_gitify_yml` — the working tree's `gitify.yml.exported_at` is newer than the commit's, suggesting an unsaved export. Details: `{working_tree_exported_at, head_exported_at}`.

Schema mismatch is best-effort with a warning, not a hard error: v2 must still be able to read v1 trees (per [CLAUDE.md hard rule #5](../CLAUDE.md)), so cross-version diffing is observable but non-blocking.

### Polished text format

Per-entity blocks with full context plus a change summary. Per-entity, so a reader can scan the output and see "what is this card" alongside "what changed about it" without scrolling between sections.

```
== note abc123  [苦 / kǔ / bitter] ==
  deck:     Japanese::Vocab
  notetype: Hanzi-Pinyin-English
  tags:     hsk1, vocab
  fields:
    Hànzì:   苦
    pīnyīn:  ku3   →  kǔ
    English: bitter

  ~~ changes ~~
    tags  + covered
    field pīnyīn:
      - ku3
      + kǔ
```

Conventions:

- Headers fenced by `==` for entities and `~~` for the changes sub-block. Stable anchors a regex or jq-like text consumer can rely on.
- Single-line field edits render as `field-name: before → after`.
- Multi-line field/template/CSS edits render as a colorized unified diff (green `+`, red `-`).
- ANSI color is on by default for TTYs and off when stdout isn't a terminal; `--color` overrides.
- No truncation by default (the whole point is to see what changed); `--abbrev` opts into eliding very long content.
- Added entities render the full snapshot in a `++ added` block; removed entities render in a `-- removed` block; same fence style.

### Module layout

New peer module under `src/anki_gitify/`:

```
src/anki_gitify/diff/
  __init__.py
  differ.py            # orchestrator: load rev_a, load rev_b, compute model, hand to renderer
  model.py             # pydantic records: DiffEnvelope, RevRef, NoteDiff, NotetypeDiff, etc.
  comparators.py       # per-entity diff logic — pure functions taking two pydantic models, returning the changes block
  git_revs.py          # `git worktree add` / `remove` lifecycle; tempdir management
  renderers/
    __init__.py
    json_renderer.py
    text_renderer.py
```

`cli.py` gets a `diff` typer command that calls `differ.run(rev_a, rev_b, format, ...) -> int` and returns the exit code. The diff `schema_version` constant lives in `model.py`.

### Test strategy

Tests live in `tests/test_diff.py` and reuse the existing synthetic fixtures (`fixture_basic`, `fixture_with_filtered`) from `tests/conftest.py`. The pattern:

- Mutation-fixture matrix: a `tests/diff_mutations/` helper applies a specific mutation to a base gitified tree (tag added, field edited, note moved between decks, notetype renamed, field added to notetype, template HTML edited, CSS edited, filtered-deck search edited, deck added, media added). One test per mutation.
- For each mutation, assert on the JSON shape via a golden file under `tests/golden/diff/<mutation>.json`. Golden files pin the contract; intentional shape changes touch them in the same commit.
- For each mutation, also assert that the polished-text output contains expected anchors (entity header, change-block fence, the specific delta phrase). Avoids brittle full-text comparison.
- One end-to-end test that builds two distinct fixtures, commits each as a separate git commit in a tempdir, runs `anki-gitify diff <sha_a> <sha_b>` via the typer test client, and verifies the worktree-add/remove lifecycle.

### Diff `schema_version` history

| version | introduced in | notes |
|---|---|---|
| 1 | v0.3.0 | Initial contract |

Bump rules: any backward-incompatible JSON-shape change (key removed, key renamed, value type changed, `kind` semantics changed) bumps this number and adds a row above. Adding a new key, a new warning `kind`, or a new top-level entity section is non-breaking and does not bump.

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
