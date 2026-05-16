"""Per-entity diff logic.

Each function takes two indexed snapshot dicts (keyed by the entity's stable
identifier: `notes.guid`, `notetypes.name`, etc.) and returns the
`{added, removed, changed}` triple. All shape decisions live in
[`model.py`](model.py); these functions only compute the deltas.
"""

from __future__ import annotations

import difflib

from .model import (
    CardOverrideChange,
    CardOverrideEdge,
    ChangedFilteredDeck,
    ChangedNote,
    ChangedNotetype,
    DeckMoveChange,
    FieldOrderChange,
    FilteredDeckChanges,
    FilteredDeckSnapshot,
    MediaEntry,
    NoteChanges,
    NoteFieldChange,
    NoteSnapshot,
    NotetypeChanges,
    NotetypeFieldChange,
    NotetypeFieldPropsDelta,
    NotetypeFieldSnapshot,
    NotetypeRefChange,
    NotetypeSnapshot,
    NotetypeTemplateChange,
    NotetypeTemplateSnapshot,
    ScalarChange,
    TextDelta,
)


def unified_diff(before: str, after: str, n: int = 3) -> str:
    """Return a unified diff string; empty when `before == after`."""
    if before == after:
        return ""
    bl = before.splitlines(keepends=False)
    al = after.splitlines(keepends=False)
    out = list(difflib.unified_diff(bl, al, n=n, lineterm=""))
    if not out:
        return ""
    return "\n".join(out) + "\n"


# ---------- Notes ----------


def diff_notes(
    before: dict[str, NoteSnapshot],
    after: dict[str, NoteSnapshot],
) -> tuple[list[NoteSnapshot], list[NoteSnapshot], list[ChangedNote]]:
    keys_before = set(before)
    keys_after = set(after)
    added = [after[k] for k in sorted(keys_after - keys_before)]
    removed = [before[k] for k in sorted(keys_before - keys_after)]
    changed: list[ChangedNote] = []
    for k in sorted(keys_before & keys_after):
        b, a = before[k], after[k]
        changes = _diff_one_note(b, a)
        if _note_changes_nonempty(changes):
            changed.append(ChangedNote(before=b, after=a, changes=changes))
    return added, removed, changed


def _diff_one_note(b: NoteSnapshot, a: NoteSnapshot) -> NoteChanges:
    tags_b = set(b.tags)
    tags_a = set(a.tags)
    tags_added = sorted(tags_a - tags_b)
    tags_removed = sorted(tags_b - tags_a)

    deck_moved = (
        DeckMoveChange(before=b.deck_path, after=a.deck_path)
        if b.deck_path != a.deck_path
        else None
    )

    notetype_changed = (
        NotetypeRefChange(before=b.notetype_name, after=a.notetype_name)
        if b.notetype_name != a.notetype_name
        else None
    )

    # Field changes: keyed by field name. When the notetype changes the field
    # set can differ between sides; we walk the union and emit one entry per
    # name whose value differs.
    fields_b = {f.name: f.value for f in b.fields}
    fields_a = {f.name: f.value for f in a.fields}
    fields_changed: list[NoteFieldChange] = []
    for name in sorted(set(fields_b) | set(fields_a)):
        bv = fields_b.get(name, "")
        av = fields_a.get(name, "")
        if bv != av:
            fields_changed.append(
                NoteFieldChange(
                    name=name,
                    before=bv,
                    after=av,
                    unified_diff=unified_diff(bv, av),
                )
            )

    # Card overrides: key by ord, emit add/remove/change rows.
    overrides_b = {ov.ord: ov.deck_path for ov in b.card_overrides}
    overrides_a = {ov.ord: ov.deck_path for ov in a.card_overrides}
    card_overrides_changed: list[CardOverrideChange] = []
    for ord_idx in sorted(set(overrides_b) | set(overrides_a)):
        bv = overrides_b.get(ord_idx)
        av = overrides_a.get(ord_idx)
        if bv == av:
            continue
        card_overrides_changed.append(
            CardOverrideChange(
                ord=ord_idx,
                before=CardOverrideEdge(deck_path=bv) if bv is not None else None,
                after=CardOverrideEdge(deck_path=av) if av is not None else None,
            )
        )

    return NoteChanges(
        tags_added=tags_added,
        tags_removed=tags_removed,
        deck_moved=deck_moved,
        notetype_changed=notetype_changed,
        fields_changed=fields_changed,
        card_overrides_changed=card_overrides_changed,
    )


def _note_changes_nonempty(c: NoteChanges) -> bool:
    return bool(
        c.tags_added
        or c.tags_removed
        or c.deck_moved is not None
        or c.notetype_changed is not None
        or c.fields_changed
        or c.card_overrides_changed
    )


# ---------- Notetypes ----------


def diff_notetypes(
    before: dict[str, NotetypeSnapshot],
    after: dict[str, NotetypeSnapshot],
) -> tuple[list[NotetypeSnapshot], list[NotetypeSnapshot], list[ChangedNotetype]]:
    keys_before = set(before)
    keys_after = set(after)
    added = [after[k] for k in sorted(keys_after - keys_before)]
    removed = [before[k] for k in sorted(keys_before - keys_after)]
    changed: list[ChangedNotetype] = []
    for k in sorted(keys_before & keys_after):
        b, a = before[k], after[k]
        changes = _diff_one_notetype(b, a)
        if _notetype_changes_nonempty(changes):
            changed.append(ChangedNotetype(before=b, after=a, changes=changes))
    return added, removed, changed


def _diff_one_notetype(b: NotetypeSnapshot, a: NotetypeSnapshot) -> NotetypeChanges:
    sort_field_changed = (
        ScalarChange(before=b.sort_field_index, after=a.sort_field_index)
        if b.sort_field_index != a.sort_field_index
        else None
    )

    fields_changed, field_order_changed = _diff_notetype_fields(b.fields, a.fields)

    templates_changed = _diff_templates(b.templates, a.templates)

    css_changed = _text_delta(b.css, a.css)
    latex_pre_changed = _text_delta(b.latex_pre, a.latex_pre)
    latex_post_changed = _text_delta(b.latex_post, a.latex_post)

    return NotetypeChanges(
        sort_field_index_changed=sort_field_changed,
        fields_changed=fields_changed,
        field_order_changed=field_order_changed,
        templates_changed=templates_changed,
        css_changed=css_changed,
        latex_pre_changed=latex_pre_changed,
        latex_post_changed=latex_post_changed,
    )


def _notetype_changes_nonempty(c: NotetypeChanges) -> bool:
    return bool(
        c.sort_field_index_changed is not None
        or c.fields_changed
        or c.field_order_changed is not None
        or c.templates_changed
        or c.css_changed is not None
        or c.latex_pre_changed is not None
        or c.latex_post_changed is not None
    )


def _diff_notetype_fields(
    b_fields: list[NotetypeFieldSnapshot],
    a_fields: list[NotetypeFieldSnapshot],
) -> tuple[list[NotetypeFieldChange], FieldOrderChange | None]:
    b_by_name = {f.name: (i, f) for i, f in enumerate(b_fields)}
    a_by_name = {f.name: (i, f) for i, f in enumerate(a_fields)}

    changes: list[NotetypeFieldChange] = []

    added_names = [f.name for f in a_fields if f.name not in b_by_name]
    removed_names = [f.name for f in b_fields if f.name not in a_by_name]
    common_names = [f.name for f in b_fields if f.name in a_by_name]

    for name in removed_names:
        idx, fld = b_by_name[name]
        changes.append(
            NotetypeFieldChange(
                status="removed",
                name=name,
                index=idx,
                font=fld.font,
                size=fld.size,
                sticky=fld.sticky,
                rtl=fld.rtl,
                plain_text=fld.plain_text,
                description=fld.description,
            )
        )
    for name in added_names:
        idx, fld = a_by_name[name]
        changes.append(
            NotetypeFieldChange(
                status="added",
                name=name,
                index=idx,
                font=fld.font,
                size=fld.size,
                sticky=fld.sticky,
                rtl=fld.rtl,
                plain_text=fld.plain_text,
                description=fld.description,
            )
        )
    for name in common_names:
        _, bf = b_by_name[name]
        _, af = a_by_name[name]
        before_props, after_props = _field_props_delta(bf, af)
        if before_props is not None:
            changes.append(
                NotetypeFieldChange(
                    status="changed",
                    name=name,
                    before=before_props,
                    after=after_props,
                )
            )

    # field_order_changed: only when the set is unchanged but indices moved.
    field_order_changed = None
    if not added_names and not removed_names:
        b_names = [f.name for f in b_fields]
        a_names = [f.name for f in a_fields]
        if b_names != a_names:
            field_order_changed = FieldOrderChange(before=b_names, after=a_names)

    return changes, field_order_changed


def _field_props_delta(
    bf: NotetypeFieldSnapshot,
    af: NotetypeFieldSnapshot,
) -> tuple[NotetypeFieldPropsDelta | None, NotetypeFieldPropsDelta | None]:
    before_kwargs: dict = {}
    after_kwargs: dict = {}
    for attr in ("font", "size", "sticky", "rtl", "plain_text", "description"):
        bv = getattr(bf, attr)
        av = getattr(af, attr)
        if bv != av:
            before_kwargs[attr] = bv
            after_kwargs[attr] = av
    if not before_kwargs:
        return None, None
    return (
        NotetypeFieldPropsDelta(**before_kwargs),
        NotetypeFieldPropsDelta(**after_kwargs),
    )


def _diff_templates(
    b_tmpls: list[NotetypeTemplateSnapshot],
    a_tmpls: list[NotetypeTemplateSnapshot],
) -> list[NotetypeTemplateChange]:
    b_by_name = {t.name: t for t in b_tmpls}
    a_by_name = {t.name: t for t in a_tmpls}
    common = [n for n in (t.name for t in b_tmpls) if n in a_by_name]
    out: list[NotetypeTemplateChange] = []
    for name in common:
        bt = b_by_name[name]
        at = a_by_name[name]
        qfmt = _text_delta(bt.qfmt, at.qfmt)
        afmt = _text_delta(bt.afmt, at.afmt)
        bqfmt = _text_delta(bt.bqfmt, at.bqfmt)
        bafmt = _text_delta(bt.bafmt, at.bafmt)
        if any(v is not None for v in (qfmt, afmt, bqfmt, bafmt)):
            out.append(
                NotetypeTemplateChange(
                    name=name, qfmt=qfmt, afmt=afmt, bqfmt=bqfmt, bafmt=bafmt
                )
            )
    return out


def _text_delta(b: str, a: str) -> TextDelta | None:
    if b == a:
        return None
    return TextDelta(before=b, after=a, unified_diff=unified_diff(b, a))


# ---------- Filtered decks ----------


def diff_filtered_decks(
    before: dict[str, FilteredDeckSnapshot],
    after: dict[str, FilteredDeckSnapshot],
) -> tuple[
    list[FilteredDeckSnapshot], list[FilteredDeckSnapshot], list[ChangedFilteredDeck]
]:
    keys_before = set(before)
    keys_after = set(after)
    added = [after[k] for k in sorted(keys_after - keys_before)]
    removed = [before[k] for k in sorted(keys_before - keys_after)]
    changed: list[ChangedFilteredDeck] = []
    for k in sorted(keys_before & keys_after):
        b, a = before[k], after[k]
        changes = _diff_one_filtered(b, a)
        if _filtered_changes_nonempty(changes) or _terms_differ(b, a):
            changed.append(ChangedFilteredDeck(before=b, after=a, changes=changes))
    return added, removed, changed


def _diff_one_filtered(
    b: FilteredDeckSnapshot, a: FilteredDeckSnapshot
) -> FilteredDeckChanges:
    # The 5 documented keys reflect terms[0] semantics when both sides have
    # exactly one term. Multi-term filtered decks (rare) leave the per-term
    # keys null; the before/after snapshots still carry the full terms list.
    bt = b.terms[0] if len(b.terms) == 1 else None
    at = a.terms[0] if len(a.terms) == 1 else None

    if bt is not None and at is not None:
        search_changed = (
            ScalarChange(before=bt.search, after=at.search) if bt.search != at.search else None
        )
        limit_changed = (
            ScalarChange(before=bt.limit, after=at.limit) if bt.limit != at.limit else None
        )
        order_changed = (
            ScalarChange(before=bt.order, after=at.order) if bt.order != at.order else None
        )
    else:
        search_changed = None
        limit_changed = None
        order_changed = None

    resched_changed = (
        ScalarChange(before=b.resched, after=a.resched) if b.resched != a.resched else None
    )
    delays_changed = (
        ScalarChange(before=b.delays, after=a.delays) if b.delays != a.delays else None
    )

    return FilteredDeckChanges(
        search_changed=search_changed,
        limit_changed=limit_changed,
        order_changed=order_changed,
        resched_changed=resched_changed,
        delays_changed=delays_changed,
    )


def _filtered_changes_nonempty(c: FilteredDeckChanges) -> bool:
    return any(
        v is not None
        for v in (
            c.search_changed,
            c.limit_changed,
            c.order_changed,
            c.resched_changed,
            c.delays_changed,
        )
    )


def _terms_differ(b: FilteredDeckSnapshot, a: FilteredDeckSnapshot) -> bool:
    return [t.model_dump() for t in b.terms] != [t.model_dump() for t in a.terms]


# ---------- Deck tree ----------


def diff_deck_tree(
    before: set[str], after: set[str]
) -> tuple[list[str], list[str]]:
    return sorted(after - before), sorted(before - after)


# ---------- Media ----------


def diff_media(
    before: dict[str, MediaEntry],
    after: dict[str, MediaEntry],
) -> tuple[list[MediaEntry], list[MediaEntry]]:
    keys_before = set(before)
    keys_after = set(after)
    added = [after[k] for k in sorted(keys_after - keys_before)]
    removed = [before[k] for k in sorted(keys_before - keys_after)]
    # A same-named file with a different hash is reported as removed+added so
    # consumers can rename-detect via content_hash without us guessing.
    for name in sorted(keys_before & keys_after):
        if before[name].content_hash != after[name].content_hash:
            removed.append(before[name])
            added.append(after[name])
    # Maintain stable ordering after the in-place append above.
    added.sort(key=lambda m: m.filename)
    removed.sort(key=lambda m: m.filename)
    return added, removed
