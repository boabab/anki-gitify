"""Render a DeckDiff as colored terminal, markdown, or JSON."""

from __future__ import annotations

import difflib
import json
from dataclasses import asdict
from typing import Protocol

import typer

from .diff import DeckDiff, NoteChange, NotetypeChange, TemplateChange


_FIELD_DIFF_MAX_LINES = 12


# --- writer protocol: TerminalWriter colors, MarkdownWriter formats ------


class _Writer(Protocol):
    def section(self, title: str) -> None: ...
    def line(self, text: str = "", *, kind: str = "plain") -> None: ...
    def code_block(self, lines: list[str]) -> None: ...


class _TerminalWriter:
    _KIND_TO_COLOR = {
        "plain": None,
        "info": typer.colors.CYAN,
        "added": typer.colors.GREEN,
        "removed": typer.colors.RED,
        "changed": typer.colors.YELLOW,
        "hunk": typer.colors.CYAN,
    }

    def section(self, title: str) -> None:
        typer.secho(f"== {title} ==", fg=typer.colors.CYAN, bold=True)

    def line(self, text: str = "", *, kind: str = "plain") -> None:
        color = self._KIND_TO_COLOR.get(kind)
        bold = kind == "title"
        if color is None and not bold:
            typer.echo(text)
        elif bold:
            typer.secho(text, fg=typer.colors.YELLOW, bold=True)
        else:
            typer.secho(text, fg=color)

    def code_block(self, lines: list[str]) -> None:
        for ln in lines:
            if ln.startswith("+"):
                typer.secho(ln, fg=typer.colors.GREEN)
            elif ln.startswith("-"):
                typer.secho(ln, fg=typer.colors.RED)
            elif ln.startswith("@@"):
                typer.secho(ln, fg=typer.colors.CYAN)
            else:
                typer.echo(ln)


class _MarkdownWriter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def section(self, title: str) -> None:
        if self.lines:
            self.lines.append("")
        self.lines.append(f"## {title}")
        self.lines.append("")

    def line(self, text: str = "", *, kind: str = "plain") -> None:
        self.lines.append(text)

    def code_block(self, lines: list[str]) -> None:
        self.lines.append("```diff")
        self.lines.extend(lines)
        self.lines.append("```")

    def getvalue(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"


# --- public entry points -------------------------------------------------


def render_terminal(diff: DeckDiff) -> None:
    _render(diff, _TerminalWriter())


def render_markdown(diff: DeckDiff) -> str:
    w = _MarkdownWriter()
    _render(diff, w)
    return w.getvalue()


def render_json(diff: DeckDiff) -> str:
    return json.dumps(asdict(diff), indent=2, ensure_ascii=False, sort_keys=True)


# --- shared body --------------------------------------------------------


def _render(diff: DeckDiff, w: _Writer) -> None:
    if diff.is_empty():
        w.line("No semantic changes.", kind="added")
        return

    w.section("Summary")
    _summary(diff, w)

    if diff.notes.added or diff.notes.removed or diff.notes.changed or diff.notes.migrated_notetype:
        w.section("Notes")
        _render_notes(diff, w)

    if diff.notetypes.added or diff.notetypes.removed or diff.notetypes.changed:
        w.section("Notetypes")
        _render_notetypes(diff, w)

    if diff.filtered_decks.added or diff.filtered_decks.removed or diff.filtered_decks.changed:
        w.section("Filtered decks")
        _render_filtered(diff, w)

    if diff.deck_tree.added or diff.deck_tree.removed:
        w.section("Deck tree")
        for d in diff.deck_tree.added:
            w.line(f"- `+` {d}" if isinstance(w, _MarkdownWriter) else f"  + {d}", kind="added")
        for d in diff.deck_tree.removed:
            w.line(f"- `-` {d}" if isinstance(w, _MarkdownWriter) else f"  - {d}", kind="removed")

    if diff.media.added or diff.media.removed:
        w.section("Media")
        for m in diff.media.added:
            w.line(f"- `+` {m}" if isinstance(w, _MarkdownWriter) else f"  + {m}", kind="added")
        for m in diff.media.removed:
            w.line(f"- `-` {m}" if isinstance(w, _MarkdownWriter) else f"  - {m}", kind="removed")


def _summary(diff: DeckDiff, w: _Writer) -> None:
    bits = []
    n = diff.notes
    if n.added or n.removed or n.changed or n.migrated_notetype:
        b = f"notes: +{len(n.added)} -{len(n.removed)} ~{len(n.changed)}"
        if n.migrated_notetype:
            b += f" migrated={len(n.migrated_notetype)}"
        bits.append(b)
    nt = diff.notetypes
    if nt.added or nt.removed or nt.changed:
        bits.append(f"notetypes: +{len(nt.added)} -{len(nt.removed)} ~{len(nt.changed)}")
    fd = diff.filtered_decks
    if fd.added or fd.removed or fd.changed:
        bits.append(f"filtered decks: +{len(fd.added)} -{len(fd.removed)} ~{len(fd.changed)}")
    dt = diff.deck_tree
    if dt.added or dt.removed:
        bits.append(f"decks: +{len(dt.added)} -{len(dt.removed)}")
    m = diff.media
    if m.added or m.removed:
        bits.append(f"media: +{len(m.added)} -{len(m.removed)}")
    for b in bits:
        w.line(f"- {b}" if isinstance(w, _MarkdownWriter) else f"  {b}")


def _render_notes(diff: DeckDiff, w: _Writer) -> None:
    md = isinstance(w, _MarkdownWriter)
    for mig in diff.notes.migrated_notetype:
        prefix = "- " if md else "  "
        w.line(
            f"{prefix}~ note {mig.guid} [{mig.label}]  notetype: "
            f"{mig.from_slug} -> {mig.to_slug}",
            kind="changed",
        )
    for n in diff.notes.added:
        prefix = "- " if md else "  "
        w.line(
            f"{prefix}+ note {n.guid} [{n.label}]  notetype={n.notetype_slug}  "
            f"deck={n.deck_path}",
            kind="added",
        )
    for n in diff.notes.removed:
        prefix = "- " if md else "  "
        w.line(
            f"{prefix}- note {n.guid} [{n.label}]  notetype={n.notetype_slug}  "
            f"deck={n.deck_path}",
            kind="removed",
        )
    for c in diff.notes.changed:
        _render_note_change(c, w, md)


def _render_note_change(c: NoteChange, w: _Writer, md: bool) -> None:
    prefix = "### " if md else "  ~ "
    suffix = "" if md else "  (notetype=" + c.notetype_slug + ")"
    title_text = (
        f"{prefix}note {c.guid} [{c.label}]"
        + (f" (notetype={c.notetype_slug})" if md else suffix)
    )
    w.line(title_text, kind="title")

    inner = "    " if md else "      "
    if c.deck_path_before is not None and c.deck_path_after is not None:
        w.line(f"{inner}deck: {c.deck_path_before} -> {c.deck_path_after}", kind="changed")
    if c.tags_added:
        w.line(f"{inner}tags added:   {' '.join(c.tags_added)}", kind="added")
    if c.tags_removed:
        w.line(f"{inner}tags removed: {' '.join(c.tags_removed)}", kind="removed")
    for fc in c.fields_changed:
        w.line(f"{inner}field '{fc.name}':")
        block = _truncated_unified_diff(fc.before, fc.after)
        if md:
            w.code_block(block)
        else:
            indented = [f"{inner}  {ln}" for ln in block]
            w.code_block(indented)
    for ov in c.card_overrides_changed:
        if ov.before is None:
            w.line(
                f"{inner}card ord {ov.ord}: deck override added -> {ov.after}",
                kind="added",
            )
        elif ov.after is None:
            w.line(
                f"{inner}card ord {ov.ord}: deck override removed (was {ov.before})",
                kind="removed",
            )
        else:
            w.line(
                f"{inner}card ord {ov.ord}: {ov.before} -> {ov.after}",
                kind="changed",
            )


def _truncated_unified_diff(before: str, after: str) -> list[str]:
    raw = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            lineterm="",
            n=2,
        )
    )
    body = [ln for ln in raw if not (ln.startswith("---") or ln.startswith("+++"))]
    if not body:
        # whitespace-only or newline-only changes — show literal
        body = [f"- {before!r}", f"+ {after!r}"]
    if len(body) > _FIELD_DIFF_MAX_LINES:
        body = body[:_FIELD_DIFF_MAX_LINES] + [
            f"... ({len(body) - _FIELD_DIFF_MAX_LINES} more lines)"
        ]
    return body


def _render_notetypes(diff: DeckDiff, w: _Writer) -> None:
    md = isinstance(w, _MarkdownWriter)
    for n in diff.notetypes.added:
        prefix = "- " if md else "  "
        w.line(f"{prefix}+ notetype: {n}", kind="added")
    for n in diff.notetypes.removed:
        prefix = "- " if md else "  "
        w.line(f"{prefix}- notetype: {n}", kind="removed")
    for c in diff.notetypes.changed:
        _render_notetype_change(c, w, md)


def _render_notetype_change(c: NotetypeChange, w: _Writer, md: bool) -> None:
    title = f"### notetype: {c.name}" if md else f"  ~ notetype: {c.name}"
    w.line(title, kind="title")
    inner = "    " if md else "      "
    for k, pair in c.meta_changes.items():
        before, after = pair
        w.line(f"{inner}{k}: {before!r} -> {after!r}", kind="changed")
    for f in c.fields_added:
        w.line(f"{inner}+ field: {f}", kind="added")
    for f in c.fields_removed:
        w.line(f"{inner}- field: {f}", kind="removed")
    for pair in c.fields_renamed:
        w.line(f"{inner}~ field: {pair[0]} -> {pair[1]}", kind="changed")
    if c.css_changed:
        w.line(f"{inner}css changed:")
        _emit_diff(c.css_diff, w, inner, md)
    for t in c.templates_added:
        w.line(f"{inner}+ template: {t}", kind="added")
    for t in c.templates_removed:
        w.line(f"{inner}- template: {t}", kind="removed")
    for t in c.templates_changed:
        _render_template_change(t, w, md, inner)


def _render_template_change(t: TemplateChange, w: _Writer, md: bool, base_indent: str) -> None:
    w.line(f"{base_indent}~ template (ord {t.ordinal}): {t.name}", kind="changed")
    inner = base_indent + "    "
    if t.qfmt_changed:
        w.line(f"{inner}front.html:")
        _emit_diff(t.qfmt_diff, w, inner, md)
    if t.afmt_changed:
        w.line(f"{inner}back.html:")
        _emit_diff(t.afmt_diff, w, inner, md)
    if t.bqfmt_changed:
        w.line(f"{inner}browser_front.html:")
        _emit_diff(t.bqfmt_diff, w, inner, md)
    if t.bafmt_changed:
        w.line(f"{inner}browser_back.html:")
        _emit_diff(t.bafmt_diff, w, inner, md)


def _emit_diff(diff_text: str, w: _Writer, indent: str, md: bool) -> None:
    lines = diff_text.splitlines()
    body = [ln for ln in lines if not (ln.startswith("---") or ln.startswith("+++"))]
    if len(body) > _FIELD_DIFF_MAX_LINES:
        body = body[:_FIELD_DIFF_MAX_LINES] + [
            f"... ({len(body) - _FIELD_DIFF_MAX_LINES} more lines)"
        ]
    if md:
        w.code_block(body)
    else:
        w.code_block([f"{indent}  {ln}" for ln in body])


def _render_filtered(diff: DeckDiff, w: _Writer) -> None:
    md = isinstance(w, _MarkdownWriter)
    for n in diff.filtered_decks.added:
        prefix = "- " if md else "  "
        w.line(f"{prefix}+ filtered deck: {n}", kind="added")
    for n in diff.filtered_decks.removed:
        prefix = "- " if md else "  "
        w.line(f"{prefix}- filtered deck: {n}", kind="removed")
    for c in diff.filtered_decks.changed:
        title = f"### filtered deck: {c.name}" if md else f"  ~ filtered deck: {c.name}"
        w.line(title, kind="title")
        inner = "    " if md else "      "
        for k in sorted(set(c.before) | set(c.after)):
            vb = c.before.get(k)
            va = c.after.get(k)
            if vb != va:
                w.line(f"{inner}{k}: {vb!r} -> {va!r}", kind="changed")
