"""Semantic comparison of two LoadedRepo snapshots.

This is the data-producing half of the diff command: it walks two gitified
repos already in memory (via ``importer.loader.load``) and returns a
:class:`DeckDiff` describing the differences. The renderers in ``render.py``
turn that into text. The dataclasses use only plain types so
``dataclasses.asdict`` yields JSON-serializable output.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from ..importer.loader import (
    LoadedCardOverride,
    LoadedNote,
    LoadedNoteType,
    LoadedRepo,
)


@dataclass
class FieldChange:
    name: str
    before: str
    after: str


@dataclass
class CardOverrideChange:
    ord: int
    before: str | None  # None means override was added
    after: str | None   # None means override was removed


@dataclass
class NoteRef:
    notetype_slug: str
    guid: str
    deck_path: str
    label: str  # short preview of the sort field for display


@dataclass
class NoteChange:
    notetype_slug: str
    guid: str
    label: str
    deck_path_before: str | None  # set only if changed
    deck_path_after: str | None
    tags_added: list[str] = field(default_factory=list)
    tags_removed: list[str] = field(default_factory=list)
    fields_changed: list[FieldChange] = field(default_factory=list)
    card_overrides_changed: list[CardOverrideChange] = field(default_factory=list)


@dataclass
class NoteTypeMigration:
    guid: str
    label: str
    from_slug: str
    to_slug: str


@dataclass
class NotesDiff:
    added: list[NoteRef] = field(default_factory=list)
    removed: list[NoteRef] = field(default_factory=list)
    changed: list[NoteChange] = field(default_factory=list)
    migrated_notetype: list[NoteTypeMigration] = field(default_factory=list)


@dataclass
class TemplateChange:
    name: str
    ordinal: int
    qfmt_changed: bool
    qfmt_diff: str
    afmt_changed: bool
    afmt_diff: str
    bqfmt_changed: bool
    bqfmt_diff: str
    bafmt_changed: bool
    bafmt_diff: str


@dataclass
class NotetypeChange:
    name: str
    meta_changes: dict[str, list[Any]]  # {key: [before, after]}
    fields_added: list[str] = field(default_factory=list)
    fields_removed: list[str] = field(default_factory=list)
    fields_renamed: list[list[str]] = field(default_factory=list)  # [[before, after], ...]
    css_changed: bool = False
    css_diff: str = ""
    templates_added: list[str] = field(default_factory=list)
    templates_removed: list[str] = field(default_factory=list)
    templates_changed: list[TemplateChange] = field(default_factory=list)


@dataclass
class NotetypesDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[NotetypeChange] = field(default_factory=list)


@dataclass
class FilteredDeckChange:
    name: str
    before: dict
    after: dict


@dataclass
class FilteredDecksDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[FilteredDeckChange] = field(default_factory=list)


@dataclass
class DeckTreeDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


@dataclass
class MediaDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


@dataclass
class MetadataDiff:
    schema_version_before: int
    schema_version_after: int
    root_deck_before: str
    root_deck_after: str


@dataclass
class DeckDiff:
    notes: NotesDiff = field(default_factory=NotesDiff)
    notetypes: NotetypesDiff = field(default_factory=NotetypesDiff)
    filtered_decks: FilteredDecksDiff = field(default_factory=FilteredDecksDiff)
    deck_tree: DeckTreeDiff = field(default_factory=DeckTreeDiff)
    media: MediaDiff = field(default_factory=MediaDiff)
    metadata: MetadataDiff | None = None

    def is_empty(self) -> bool:
        return (
            not self.notes.added
            and not self.notes.removed
            and not self.notes.changed
            and not self.notes.migrated_notetype
            and not self.notetypes.added
            and not self.notetypes.removed
            and not self.notetypes.changed
            and not self.filtered_decks.added
            and not self.filtered_decks.removed
            and not self.filtered_decks.changed
            and not self.deck_tree.added
            and not self.deck_tree.removed
            and not self.media.added
            and not self.media.removed
        )


def compute_diff(a: LoadedRepo, b: LoadedRepo) -> DeckDiff:
    return DeckDiff(
        notes=_diff_notes(a, b),
        notetypes=_diff_notetypes(a, b),
        filtered_decks=_diff_filtered(a, b),
        deck_tree=_diff_deck_tree(a, b),
        media=_diff_media(a, b),
        metadata=_diff_metadata(a, b),
    )


# --- notes ---------------------------------------------------------------


_HTML_TAG = __import__("re").compile(r"<[^>]+>")


def _note_label(note: LoadedNote, by_slug: dict[str, LoadedNoteType]) -> str:
    nt = by_slug.get(note.notetype_slug)
    if nt is not None and 0 <= nt.sort_field_index < len(note.fields):
        val = note.fields[nt.sort_field_index]
    else:
        val = note.fields[0] if note.fields else ""
    text = _HTML_TAG.sub("", val).strip().replace("\n", " ")
    return (text[:37] + "...") if len(text) > 40 else (text or "(empty)")


def _diff_notes(a: LoadedRepo, b: LoadedRepo) -> NotesDiff:
    a_by_slug = {nt.slug: nt for nt in a.notetypes}
    b_by_slug = {nt.slug: nt for nt in b.notetypes}

    a_idx: dict[tuple[str, str], LoadedNote] = {(n.notetype_slug, n.guid): n for n in a.notes}
    b_idx: dict[tuple[str, str], LoadedNote] = {(n.notetype_slug, n.guid): n for n in b.notes}

    # Detect notetype migrations: same guid, different notetype_slug between the two sides.
    a_by_guid: dict[str, list[LoadedNote]] = {}
    for n in a.notes:
        a_by_guid.setdefault(n.guid, []).append(n)
    b_by_guid: dict[str, list[LoadedNote]] = {}
    for n in b.notes:
        b_by_guid.setdefault(n.guid, []).append(n)

    migrated: list[NoteTypeMigration] = []
    migrated_keys_a: set[tuple[str, str]] = set()
    migrated_keys_b: set[tuple[str, str]] = set()
    for guid in sorted(a_by_guid.keys() & b_by_guid.keys()):
        a_slugs = {n.notetype_slug for n in a_by_guid[guid]}
        b_slugs = {n.notetype_slug for n in b_by_guid[guid]}
        if a_slugs == b_slugs:
            continue
        # only a clean one-to-one move counts as a migration (avoids classifying
        # multi-notetype edge cases as migrations)
        if len(a_slugs) == 1 and len(b_slugs) == 1:
            old = next(iter(a_slugs))
            new = next(iter(b_slugs))
            an = a_by_guid[guid][0]
            bn = b_by_guid[guid][0]
            migrated.append(
                NoteTypeMigration(
                    guid=guid,
                    label=_note_label(bn, b_by_slug) or _note_label(an, a_by_slug),
                    from_slug=old,
                    to_slug=new,
                )
            )
            migrated_keys_a.add((old, guid))
            migrated_keys_b.add((new, guid))

    added_refs: list[NoteRef] = []
    removed_refs: list[NoteRef] = []
    for k, n in b_idx.items():
        if k in a_idx or k in migrated_keys_b:
            continue
        added_refs.append(
            NoteRef(
                notetype_slug=n.notetype_slug,
                guid=n.guid,
                deck_path=n.deck_path,
                label=_note_label(n, b_by_slug),
            )
        )
    for k, n in a_idx.items():
        if k in b_idx or k in migrated_keys_a:
            continue
        removed_refs.append(
            NoteRef(
                notetype_slug=n.notetype_slug,
                guid=n.guid,
                deck_path=n.deck_path,
                label=_note_label(n, a_by_slug),
            )
        )
    added_refs.sort(key=lambda r: (r.notetype_slug, r.deck_path, r.guid))
    removed_refs.sort(key=lambda r: (r.notetype_slug, r.deck_path, r.guid))

    a_ov_by_note: dict[str, dict[int, str]] = {}
    for o in a.card_overrides:
        a_ov_by_note.setdefault(o.note_guid, {})[o.ord] = o.deck_path
    b_ov_by_note: dict[str, dict[int, str]] = {}
    for o in b.card_overrides:
        b_ov_by_note.setdefault(o.note_guid, {})[o.ord] = o.deck_path

    changed: list[NoteChange] = []
    for key in sorted(a_idx.keys() & b_idx.keys()):
        an = a_idx[key]
        bn = b_idx[key]
        nt = b_by_slug.get(bn.notetype_slug) or a_by_slug.get(an.notetype_slug)
        field_names = nt.field_names if nt is not None else []

        deck_before = an.deck_path if an.deck_path != bn.deck_path else None
        deck_after = bn.deck_path if an.deck_path != bn.deck_path else None

        a_tags = set(an.tags)
        b_tags = set(bn.tags)
        tags_added = sorted(b_tags - a_tags)
        tags_removed = sorted(a_tags - b_tags)

        fields_changed: list[FieldChange] = []
        for i in range(max(len(an.fields), len(bn.fields))):
            va = an.fields[i] if i < len(an.fields) else ""
            vb = bn.fields[i] if i < len(bn.fields) else ""
            if va != vb:
                name = field_names[i] if i < len(field_names) else f"field {i}"
                fields_changed.append(FieldChange(name=name, before=va, after=vb))

        ov_changes = _override_changes_for(an.guid, a_ov_by_note, b_ov_by_note)

        if (
            deck_before is None
            and not tags_added
            and not tags_removed
            and not fields_changed
            and not ov_changes
        ):
            continue

        changed.append(
            NoteChange(
                notetype_slug=bn.notetype_slug,
                guid=bn.guid,
                label=_note_label(bn, b_by_slug),
                deck_path_before=deck_before,
                deck_path_after=deck_after,
                tags_added=tags_added,
                tags_removed=tags_removed,
                fields_changed=fields_changed,
                card_overrides_changed=ov_changes,
            )
        )

    # Card-override changes for notes that didn't otherwise change also matter —
    # surface them as their own NoteChange entries with no field/tag/deck delta.
    notes_already_changed = {(c.notetype_slug, c.guid) for c in changed}
    for key in sorted(a_idx.keys() & b_idx.keys()):
        if key in notes_already_changed:
            continue
        notetype_slug, guid = key
        ov_changes = _override_changes_for(guid, a_ov_by_note, b_ov_by_note)
        if not ov_changes:
            continue
        bn = b_idx[key]
        changed.append(
            NoteChange(
                notetype_slug=notetype_slug,
                guid=guid,
                label=_note_label(bn, b_by_slug),
                deck_path_before=None,
                deck_path_after=None,
                tags_added=[],
                tags_removed=[],
                fields_changed=[],
                card_overrides_changed=ov_changes,
            )
        )

    changed.sort(key=lambda c: (c.notetype_slug, c.guid))
    return NotesDiff(
        added=added_refs,
        removed=removed_refs,
        changed=changed,
        migrated_notetype=migrated,
    )


def _override_changes_for(
    guid: str,
    a_by_note: dict[str, dict[int, str]],
    b_by_note: dict[str, dict[int, str]],
) -> list[CardOverrideChange]:
    a_ords = a_by_note.get(guid, {})
    b_ords = b_by_note.get(guid, {})
    out: list[CardOverrideChange] = []
    for ord_ in sorted(set(a_ords) | set(b_ords)):
        before = a_ords.get(ord_)
        after = b_ords.get(ord_)
        if before != after:
            out.append(CardOverrideChange(ord=ord_, before=before, after=after))
    return out


# --- notetypes -----------------------------------------------------------


def _diff_notetypes(a: LoadedRepo, b: LoadedRepo) -> NotetypesDiff:
    a_idx = {nt.name: nt for nt in a.notetypes}
    b_idx = {nt.name: nt for nt in b.notetypes}
    added = sorted(set(b_idx) - set(a_idx))
    removed = sorted(set(a_idx) - set(b_idx))

    changed: list[NotetypeChange] = []
    for name in sorted(set(a_idx) & set(b_idx)):
        an = a_idx[name]
        bn = b_idx[name]
        meta_changes: dict[str, list[Any]] = {}
        for k in ("kind", "sort_field_index", "latex_pre", "latex_post"):
            va = getattr(an, k)
            vb = getattr(bn, k)
            if va != vb:
                meta_changes[k] = [va, vb]

        a_names = an.field_names
        b_names = bn.field_names
        fields_added: list[str] = []
        fields_removed: list[str] = []
        fields_renamed: list[list[str]] = []
        for i in range(max(len(a_names), len(b_names))):
            ax = a_names[i] if i < len(a_names) else None
            bx = b_names[i] if i < len(b_names) else None
            if ax is None and bx is not None:
                fields_added.append(bx)
            elif bx is None and ax is not None:
                fields_removed.append(ax)
            elif ax != bx and ax is not None and bx is not None:
                fields_renamed.append([ax, bx])

        css_changed = an.css != bn.css
        css_diff = _unified(an.css, bn.css) if css_changed else ""

        a_tmpls = {t.ordinal: t for t in an.templates}
        b_tmpls = {t.ordinal: t for t in bn.templates}
        tmpl_added = [b_tmpls[o].name for o in sorted(set(b_tmpls) - set(a_tmpls))]
        tmpl_removed = [a_tmpls[o].name for o in sorted(set(a_tmpls) - set(b_tmpls))]
        tmpl_changed: list[TemplateChange] = []
        for ord_ in sorted(set(a_tmpls) & set(b_tmpls)):
            at = a_tmpls[ord_]
            bt = b_tmpls[ord_]
            q_changed = at.qfmt != bt.qfmt
            af_changed = at.afmt != bt.afmt
            bq_changed = (at.bqfmt or "") != (bt.bqfmt or "")
            ba_changed = (at.bafmt or "") != (bt.bafmt or "")
            renamed = at.name != bt.name
            if not (q_changed or af_changed or bq_changed or ba_changed or renamed):
                continue
            tmpl_changed.append(
                TemplateChange(
                    name=bt.name,
                    ordinal=ord_,
                    qfmt_changed=q_changed,
                    qfmt_diff=_unified(at.qfmt, bt.qfmt) if q_changed else "",
                    afmt_changed=af_changed,
                    afmt_diff=_unified(at.afmt, bt.afmt) if af_changed else "",
                    bqfmt_changed=bq_changed,
                    bqfmt_diff=_unified(at.bqfmt or "", bt.bqfmt or "") if bq_changed else "",
                    bafmt_changed=ba_changed,
                    bafmt_diff=_unified(at.bafmt or "", bt.bafmt or "") if ba_changed else "",
                )
            )

        if not (
            meta_changes
            or fields_added
            or fields_removed
            or fields_renamed
            or css_changed
            or tmpl_added
            or tmpl_removed
            or tmpl_changed
        ):
            continue
        changed.append(
            NotetypeChange(
                name=name,
                meta_changes=meta_changes,
                fields_added=fields_added,
                fields_removed=fields_removed,
                fields_renamed=fields_renamed,
                css_changed=css_changed,
                css_diff=css_diff,
                templates_added=tmpl_added,
                templates_removed=tmpl_removed,
                templates_changed=tmpl_changed,
            )
        )

    return NotetypesDiff(added=added, removed=removed, changed=changed)


def _unified(a: str, b: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            a.splitlines(),
            b.splitlines(),
            lineterm="",
            n=3,
        )
    )


# --- filtered decks ------------------------------------------------------


def _diff_filtered(a: LoadedRepo, b: LoadedRepo) -> FilteredDecksDiff:
    a_idx = {fd.name: fd for fd in a.filtered.filtered_decks}
    b_idx = {fd.name: fd for fd in b.filtered.filtered_decks}
    added = sorted(set(b_idx) - set(a_idx))
    removed = sorted(set(a_idx) - set(b_idx))
    changed: list[FilteredDeckChange] = []
    for name in sorted(set(a_idx) & set(b_idx)):
        ad = a_idx[name].model_dump()
        bd = b_idx[name].model_dump()
        if ad != bd:
            changed.append(FilteredDeckChange(name=name, before=ad, after=bd))
    return FilteredDecksDiff(added=added, removed=removed, changed=changed)


# --- deck tree -----------------------------------------------------------


def _diff_deck_tree(a: LoadedRepo, b: LoadedRepo) -> DeckTreeDiff:
    a_set = set(a.deck_tree.full_paths)
    b_set = set(b.deck_tree.full_paths)
    return DeckTreeDiff(added=sorted(b_set - a_set), removed=sorted(a_set - b_set))


# --- media ---------------------------------------------------------------


def _diff_media(a: LoadedRepo, b: LoadedRepo) -> MediaDiff:
    a_set = {p.name for p in a.media_files}
    b_set = {p.name for p in b.media_files}
    return MediaDiff(added=sorted(b_set - a_set), removed=sorted(a_set - b_set))


# --- metadata ------------------------------------------------------------


def _diff_metadata(a: LoadedRepo, b: LoadedRepo) -> MetadataDiff:
    return MetadataDiff(
        schema_version_before=int(a.gitify.get("schema_version", 0)),
        schema_version_after=int(b.gitify.get("schema_version", 0)),
        root_deck_before=a.deck_tree.root_name,
        root_deck_after=b.deck_tree.root_name,
    )


__all__ = [
    "CardOverrideChange",
    "DeckDiff",
    "DeckTreeDiff",
    "FieldChange",
    "FilteredDeckChange",
    "FilteredDecksDiff",
    "MediaDiff",
    "MetadataDiff",
    "NoteChange",
    "NoteRef",
    "NoteTypeMigration",
    "NotesDiff",
    "NotetypeChange",
    "NotetypesDiff",
    "TemplateChange",
    "compute_diff",
    "LoadedCardOverride",  # re-export so renderers can typecheck
]
