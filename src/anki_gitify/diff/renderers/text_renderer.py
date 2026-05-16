"""Polished terminal-text renderer for diff output.

Per-entity blocks with full context plus a `~~ changes ~~` sub-block. Headers
are fenced by `==` (entities), `++` (added), `--` (removed), and `~~`
(changes). Stable anchors so a regex/jq-like text consumer can scrape the
output. ANSI color is on for TTYs by default; --color=never disables.
"""

from __future__ import annotations

from typing import Literal

from ..model import (
    CardOverrideChange,
    ChangedNote,
    ChangedNotetype,
    DiffEnvelope,
    FilteredDeckSnapshot,
    NoteChanges,
    NoteFieldChange,
    NoteSnapshot,
    NotetypeChanges,
    NotetypeFieldChange,
    NotetypeTemplateChange,
    RevRef,
    RevWorkingTree,
    ScalarChange,
    TextDelta,
)


ColorWhen = Literal["always", "auto", "never"]


class _Palette:
    def __init__(self, enabled: bool) -> None:
        if enabled:
            self.red = "\033[31m"
            self.green = "\033[32m"
            self.yellow = "\033[33m"
            self.cyan = "\033[36m"
            self.bold = "\033[1m"
            self.dim = "\033[2m"
            self.reset = "\033[0m"
        else:
            self.red = self.green = self.yellow = self.cyan = ""
            self.bold = self.dim = self.reset = ""


_FIELD_LINE_LIMIT = 80
_ABBREV_LIMIT = 200


def render(envelope: DiffEnvelope, *, color: bool, abbrev: bool) -> str:
    p = _Palette(color)
    out: list[str] = []
    out.append(_render_header(envelope, p))
    if envelope.warnings:
        out.append(_render_warnings(envelope, p))

    if envelope.is_empty():
        a = _label_for_rev(envelope.rev_a)
        b = _label_for_rev(envelope.rev_b)
        out.append(f"{p.dim}no semantic changes between {a} and {b}{p.reset}")
        return "\n".join(s for s in out if s) + "\n"

    out.extend(_render_notes(envelope, p, abbrev))
    out.extend(_render_notetypes(envelope, p, abbrev))
    out.extend(_render_filtered(envelope, p))
    out.extend(_render_deck_tree(envelope, p))
    out.extend(_render_media(envelope, p))

    out.append(_render_summary(envelope, p))
    return "\n".join(s for s in out if s is not None) + "\n"


# ---------- Header / summary ----------


def _label_for_rev(rev) -> str:
    if isinstance(rev, RevWorkingTree):
        return "<working tree>"
    if isinstance(rev, RevRef):
        return f"{rev.ref} ({rev.sha[:10]})"
    return repr(rev)


def _render_header(envelope: DiffEnvelope, p: _Palette) -> str:
    a = _label_for_rev(envelope.rev_a)
    b = _label_for_rev(envelope.rev_b)
    return (
        f"{p.bold}anki-gitify diff{p.reset}  {envelope.source.root_deck}\n"
        f"  rev_a: {a}\n"
        f"  rev_b: {b}"
    )


def _render_summary(envelope: DiffEnvelope, p: _Palette) -> str:
    s = envelope.summary
    parts = [
        f"notes +{s.notes.added} -{s.notes.removed} ~{s.notes.changed}",
        f"notetypes +{s.notetypes.added} -{s.notetypes.removed} ~{s.notetypes.changed}",
        f"filtered +{s.filtered_decks.added} -{s.filtered_decks.removed} ~{s.filtered_decks.changed}",
        f"decks +{s.decks.added} -{s.decks.removed}",
        f"media +{s.media.added} -{s.media.removed}",
    ]
    return f"\n{p.bold}summary{p.reset}  " + "  ".join(parts)


def _render_warnings(envelope: DiffEnvelope, p: _Palette) -> str:
    lines = [f"\n{p.yellow}{p.bold}warnings{p.reset}"]
    for w in envelope.warnings:
        lines.append(f"  {p.yellow}!{p.reset} [{w.kind}] {w.message}")
    return "\n".join(lines)


# ---------- Notes ----------


def _render_notes(envelope: DiffEnvelope, p: _Palette, abbrev: bool) -> list[str]:
    out: list[str] = []
    for n in envelope.notes.added:
        out.append(_render_note_added(n, p))
    for n in envelope.notes.removed:
        out.append(_render_note_removed(n, p))
    for cn in envelope.notes.changed:
        out.append(_render_note_changed(cn, p, abbrev))
    return out


def _note_label(n: NoteSnapshot) -> str:
    return n.label or n.guid


def _render_note_added(n: NoteSnapshot, p: _Palette) -> str:
    body = _render_note_body(n, p, indent="  ")
    return (
        f"\n{p.green}++ added note {n.guid}{p.reset}  [{_note_label(n)}]\n"
        f"{body}"
    )


def _render_note_removed(n: NoteSnapshot, p: _Palette) -> str:
    body = _render_note_body(n, p, indent="  ")
    return (
        f"\n{p.red}-- removed note {n.guid}{p.reset}  [{_note_label(n)}]\n"
        f"{body}"
    )


def _render_note_changed(cn: ChangedNote, p: _Palette, abbrev: bool) -> str:
    n = cn.after
    body = _render_note_body(n, p, indent="  ", changes=cn.changes)
    changes_block = _render_note_changes(cn.changes, p, abbrev)
    return (
        f"\n{p.bold}== note {n.guid}{p.reset}  [{_note_label(n)}]\n"
        f"{body}\n"
        f"  {p.cyan}~~ changes ~~{p.reset}\n"
        f"{changes_block}"
    )


def _render_note_body(
    n: NoteSnapshot,
    p: _Palette,
    indent: str,
    changes: NoteChanges | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"{indent}deck:     {n.deck_path}")
    lines.append(f"{indent}notetype: {n.notetype_name}")
    if n.tags:
        lines.append(f"{indent}tags:     {', '.join(n.tags)}")
    else:
        lines.append(f"{indent}tags:     -")
    field_change_by_name = (
        {fc.name: fc for fc in changes.fields_changed} if changes else {}
    )
    lines.append(f"{indent}fields:")
    for f in n.fields:
        if f.name in field_change_by_name:
            fc = field_change_by_name[f.name]
            if "\n" in fc.before or "\n" in fc.after or len(fc.before) > _FIELD_LINE_LIMIT or len(fc.after) > _FIELD_LINE_LIMIT:
                lines.append(f"{indent}  {f.name}:")
                lines.append(_format_multiline_change(fc.before, fc.after, p, indent + "    "))
            else:
                lines.append(
                    f"{indent}  {f.name}: "
                    f"{p.red}{fc.before}{p.reset}  →  {p.green}{fc.after}{p.reset}"
                )
        else:
            lines.append(f"{indent}  {f.name}: {_short(f.value)}")
    return "\n".join(lines)


def _render_note_changes(c: NoteChanges, p: _Palette, abbrev: bool) -> str:
    lines: list[str] = []
    if c.deck_moved:
        lines.append(
            f"    deck     {p.red}{c.deck_moved.before}{p.reset} → "
            f"{p.green}{c.deck_moved.after}{p.reset}"
        )
    if c.notetype_changed:
        lines.append(
            f"    notetype {p.red}{c.notetype_changed.before}{p.reset} → "
            f"{p.green}{c.notetype_changed.after}{p.reset}"
        )
    for t in c.tags_added:
        lines.append(f"    tags    {p.green}+ {t}{p.reset}")
    for t in c.tags_removed:
        lines.append(f"    tags    {p.red}- {t}{p.reset}")
    for fc in c.fields_changed:
        lines.append(f"    field {fc.name}:")
        lines.append(_format_field_change(fc, p, abbrev))
    for ov in c.card_overrides_changed:
        lines.append(_format_override_change(ov, p))
    return "\n".join(lines) if lines else "    (no top-level changes)"


def _format_field_change(fc: NoteFieldChange, p: _Palette, abbrev: bool) -> str:
    body_b = _maybe_abbrev(fc.before, abbrev)
    body_a = _maybe_abbrev(fc.after, abbrev)
    if "\n" not in body_b and "\n" not in body_a and len(body_b) <= _FIELD_LINE_LIMIT and len(body_a) <= _FIELD_LINE_LIMIT:
        return f"      - {p.red}{body_b}{p.reset}\n      + {p.green}{body_a}{p.reset}"
    return _format_multiline_change(body_b, body_a, p, "      ")


def _format_multiline_change(before: str, after: str, p: _Palette, indent: str) -> str:
    out: list[str] = []
    for line in before.splitlines() or [""]:
        out.append(f"{indent}{p.red}- {line}{p.reset}")
    for line in after.splitlines() or [""]:
        out.append(f"{indent}{p.green}+ {line}{p.reset}")
    return "\n".join(out)


def _format_override_change(ov: CardOverrideChange, p: _Palette) -> str:
    b = ov.before.deck_path if ov.before else None
    a = ov.after.deck_path if ov.after else None
    if b is None and a is not None:
        return f"    override ord={ov.ord} {p.green}+ {a}{p.reset}"
    if a is None and b is not None:
        return f"    override ord={ov.ord} {p.red}- {b}{p.reset}"
    return f"    override ord={ov.ord} {p.red}{b}{p.reset} → {p.green}{a}{p.reset}"


# ---------- Notetypes ----------


def _render_notetypes(envelope: DiffEnvelope, p: _Palette, abbrev: bool) -> list[str]:
    out: list[str] = []
    for nt in envelope.notetypes.added:
        out.append(
            f"\n{p.green}++ added notetype {nt.name}{p.reset}\n"
            f"  kind: {nt.kind}\n"
            f"  fields: {', '.join(f.name for f in nt.fields)}\n"
            f"  templates: {', '.join(t.name for t in nt.templates)}"
        )
    for nt in envelope.notetypes.removed:
        out.append(
            f"\n{p.red}-- removed notetype {nt.name}{p.reset}\n"
            f"  kind: {nt.kind}\n"
            f"  fields: {', '.join(f.name for f in nt.fields)}"
        )
    for cnt in envelope.notetypes.changed:
        out.append(_render_notetype_changed(cnt, p, abbrev))
    return out


def _render_notetype_changed(cnt: ChangedNotetype, p: _Palette, abbrev: bool) -> str:
    nt = cnt.after
    head = f"\n{p.bold}== notetype {nt.name}{p.reset}"
    body_lines = [
        f"  kind: {nt.kind}",
        f"  fields: {', '.join(f.name for f in nt.fields)}",
        f"  templates: {', '.join(t.name for t in nt.templates)}",
    ]
    body = "\n".join(body_lines)
    changes = _render_notetype_changes(cnt.changes, p, abbrev)
    return f"{head}\n{body}\n  {p.cyan}~~ changes ~~{p.reset}\n{changes}"


def _render_notetype_changes(c: NotetypeChanges, p: _Palette, abbrev: bool) -> str:
    lines: list[str] = []
    if c.sort_field_index_changed:
        lines.append(
            f"    sort_field_index "
            f"{p.red}{c.sort_field_index_changed.before}{p.reset} → "
            f"{p.green}{c.sort_field_index_changed.after}{p.reset}"
        )
    for fc in c.fields_changed:
        lines.append(_format_notetype_field_change(fc, p))
    if c.field_order_changed:
        fo = c.field_order_changed
        lines.append(
            f"    field order "
            f"{p.red}{', '.join(fo.before)}{p.reset} → "
            f"{p.green}{', '.join(fo.after)}{p.reset}"
        )
    for tc in c.templates_changed:
        lines.extend(_format_template_change(tc, p, abbrev))
    if c.css_changed:
        lines.append("    css:")
        lines.append(_format_multiline_change(c.css_changed.before, c.css_changed.after, p, "      "))
    if c.latex_pre_changed:
        lines.append("    latex_pre:")
        lines.append(_format_multiline_change(c.latex_pre_changed.before, c.latex_pre_changed.after, p, "      "))
    if c.latex_post_changed:
        lines.append("    latex_post:")
        lines.append(_format_multiline_change(c.latex_post_changed.before, c.latex_post_changed.after, p, "      "))
    return "\n".join(lines) if lines else "    (no top-level changes)"


def _format_notetype_field_change(fc: NotetypeFieldChange, p: _Palette) -> str:
    if fc.status == "added":
        return f"    field {p.green}+ {fc.name}{p.reset} (index {fc.index})"
    if fc.status == "removed":
        return f"    field {p.red}- {fc.name}{p.reset} (index {fc.index})"
    # changed
    parts: list[str] = []
    if fc.before is not None and fc.after is not None:
        for attr in ("font", "size", "sticky", "rtl", "plain_text", "description"):
            bv = getattr(fc.before, attr)
            av = getattr(fc.after, attr)
            if bv is not None or av is not None:
                parts.append(
                    f"{attr}={p.red}{bv}{p.reset}→{p.green}{av}{p.reset}"
                )
    return f"    field ~ {fc.name}  " + "  ".join(parts)


def _format_template_change(tc: NotetypeTemplateChange, p: _Palette, abbrev: bool) -> list[str]:
    out = [f"    template {tc.name}:"]
    for attr in ("qfmt", "afmt", "bqfmt", "bafmt"):
        slot: TextDelta | None = getattr(tc, attr)
        if slot is None:
            continue
        out.append(f"      {attr}:")
        out.append(
            _format_multiline_change(
                _maybe_abbrev(slot.before, abbrev),
                _maybe_abbrev(slot.after, abbrev),
                p,
                "        ",
            )
        )
    return out


# ---------- Filtered decks ----------


def _render_filtered(envelope: DiffEnvelope, p: _Palette) -> list[str]:
    out: list[str] = []
    for fd in envelope.filtered_decks.added:
        out.append(_render_filtered_block(fd, p, prefix=f"{p.green}++ added", color_close=p.reset))
    for fd in envelope.filtered_decks.removed:
        out.append(_render_filtered_block(fd, p, prefix=f"{p.red}-- removed", color_close=p.reset))
    for cfd in envelope.filtered_decks.changed:
        out.append(
            f"\n{p.bold}== filtered_deck {cfd.after.name}{p.reset}\n"
            + _filtered_changes_text(cfd, p)
        )
    return out


def _render_filtered_block(fd: FilteredDeckSnapshot, p: _Palette, *, prefix: str, color_close: str) -> str:
    terms = ", ".join(f"`{t.search}` (limit {t.limit}, order {t.order})" for t in fd.terms)
    return (
        f"\n{prefix} filtered_deck {fd.name}{color_close}\n"
        f"  resched: {fd.resched}  delays: {fd.delays}\n"
        f"  terms: {terms}"
    )


def _filtered_changes_text(cfd, p: _Palette) -> str:
    c = cfd.changes
    lines = ["  ~~ changes ~~"]
    for label, attr in (
        ("search", "search_changed"),
        ("limit", "limit_changed"),
        ("order", "order_changed"),
        ("resched", "resched_changed"),
        ("delays", "delays_changed"),
    ):
        val: ScalarChange | None = getattr(c, attr)
        if val is not None:
            lines.append(
                f"    {label}: {p.red}{val.before}{p.reset} → {p.green}{val.after}{p.reset}"
            )
    return "\n".join(lines)


# ---------- Deck tree ----------


def _render_deck_tree(envelope: DiffEnvelope, p: _Palette) -> list[str]:
    if not envelope.deck_tree.added and not envelope.deck_tree.removed:
        return []
    out = [f"\n{p.bold}== deck tree =={p.reset}"]
    for d in envelope.deck_tree.added:
        out.append(f"  {p.green}+ {d}{p.reset}")
    for d in envelope.deck_tree.removed:
        out.append(f"  {p.red}- {d}{p.reset}")
    return out


# ---------- Media ----------


def _render_media(envelope: DiffEnvelope, p: _Palette) -> list[str]:
    if not envelope.media.added and not envelope.media.removed:
        return []
    out = [f"\n{p.bold}== media =={p.reset}"]
    for m in envelope.media.added:
        out.append(f"  {p.green}+ {m.filename}{p.reset}  ({m.size}B  {m.content_hash[:18]}...)")
    for m in envelope.media.removed:
        out.append(f"  {p.red}- {m.filename}{p.reset}  ({m.size}B  {m.content_hash[:18]}...)")
    return out


# ---------- Helpers ----------


def _short(s: str) -> str:
    one_line = s.replace("\n", " ⏎ ")
    if len(one_line) > _FIELD_LINE_LIMIT:
        return one_line[: _FIELD_LINE_LIMIT - 3] + "..."
    return one_line


def _maybe_abbrev(s: str, abbrev: bool) -> str:
    if not abbrev or len(s) <= _ABBREV_LIMIT:
        return s
    head = s[: _ABBREV_LIMIT // 2]
    tail = s[-_ABBREV_LIMIT // 4 :]
    omitted = len(s) - len(head) - len(tail)
    return f"{head}\n... [{omitted} chars omitted] ...\n{tail}"
