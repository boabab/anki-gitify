"""Orchestrator: materialize both revs, load, snapshot, diff, render.

Public surface:
- `RevInput` (re-exported from `git_revs`).
- `run_diff(...) -> (DiffEnvelope, rendered_text)` — used by `cli.py` and
  embedders.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from pathlib import Path
from typing import Literal

from .. import __version__
from .._yaml import load_yaml
from ..importer.loader import LoadedRepo, load
from ..schema import SCHEMA_VERSION
from .comparators import (
    diff_deck_tree,
    diff_filtered_decks,
    diff_media,
    diff_notes,
    diff_notetypes,
)
from .git_revs import RevInput, find_gitified_repo, materialize_rev
from .model import (
    DIFF_SCHEMA_VERSION,
    CategorySummary,
    DeckTreeSection,
    DiffEnvelope,
    DiffSource,
    DiffSummary,
    FilteredDeckSection,
    FilteredDeckSnapshot,
    FilteredDeckTermSnapshot,
    MediaEntry,
    MediaSection,
    NoteFieldSnapshot,
    NoteSection,
    NoteSnapshot,
    NotetypeFieldSnapshot,
    NotetypeSection,
    NotetypeSnapshot,
    NotetypeTemplateSnapshot,
    CardOverrideSnapshot,
    RevRef,
    RevSpec,
    RevWorkingTree,
    TwoStateSummary,
    WarningEntry,
)
from .renderers import json_renderer, text_renderer


__all__ = ["RevInput", "run_diff"]


# ---------- Snapshot building ----------


class _Snapshot:
    """All entity dicts for one rev, ready for diffing."""

    def __init__(
        self,
        notes_by_guid: dict[str, NoteSnapshot],
        notetypes_by_name: dict[str, NotetypeSnapshot],
        filtered_by_name: dict[str, FilteredDeckSnapshot],
        deck_paths: set[str],
        media_by_filename: dict[str, MediaEntry],
        warnings: list[WarningEntry],
        rev_spec: RevSpec,
        root_deck: str,
        gitify_exported_at: str | None,
    ) -> None:
        self.notes_by_guid = notes_by_guid
        self.notetypes_by_name = notetypes_by_name
        self.filtered_by_name = filtered_by_name
        self.deck_paths = deck_paths
        self.media_by_filename = media_by_filename
        self.warnings = warnings
        self.rev_spec = rev_spec
        self.root_deck = root_deck
        self.gitify_exported_at = gitify_exported_at


def _build_snapshot(
    gitified_dir: Path,
    rev_spec: RevSpec,
    rev_label: Literal["a", "b"],
) -> _Snapshot:
    """Load the gitified dir at `gitified_dir` and convert it to a snapshot.

    Soft errors (missing gitify.yml, schema-version mismatch, unparseable
    files, unknown notetype references) are recorded as warnings on the
    returned snapshot rather than raised.
    """
    warnings: list[WarningEntry] = []

    gitify_path = gitified_dir / "gitify.yml"
    if not gitify_path.is_file():
        warnings.append(
            WarningEntry(
                kind="missing_gitify_yml",
                message=f"rev_{rev_label} has no gitify.yml at {gitify_path}",
                details={"rev": rev_label, "path": str(gitify_path)},
            )
        )
        return _empty_snapshot(rev_spec, root_deck="<unknown>", warnings=warnings)

    try:
        gitify_data = load_yaml(gitify_path)
    except Exception as exc:
        warnings.append(
            WarningEntry(
                kind="undecodable_file",
                message=f"rev_{rev_label}: could not parse gitify.yml ({exc})",
                details={"rev": rev_label, "path": str(gitify_path), "error": str(exc)},
            )
        )
        return _empty_snapshot(rev_spec, root_deck="<unknown>", warnings=warnings)

    declared_sv = int(gitify_data.get("schema_version", -1))
    if declared_sv != SCHEMA_VERSION:
        warnings.append(
            WarningEntry(
                kind="schema_mismatch",
                message=(
                    f"rev_{rev_label} declares schema_version={declared_sv}, "
                    f"this build only fully understands {SCHEMA_VERSION}. "
                    "Best-effort comparison."
                ),
                details={
                    "rev": rev_label,
                    "declared_schema_version": declared_sv,
                    "supported_schema_version": SCHEMA_VERSION,
                },
            )
        )

    try:
        repo = load(gitified_dir)
    except (ValueError, FileNotFoundError) as exc:
        warnings.append(
            WarningEntry(
                kind="undecodable_file",
                message=f"rev_{rev_label}: failed to load gitified repo ({exc})",
                details={"rev": rev_label, "error": str(exc)},
            )
        )
        return _empty_snapshot(
            rev_spec, root_deck=str(gitify_data.get("root_deck", "<unknown>")), warnings=warnings
        )

    return _convert_repo(repo, rev_spec, rev_label, warnings)


def _empty_snapshot(
    rev_spec: RevSpec, *, root_deck: str, warnings: list[WarningEntry]
) -> _Snapshot:
    return _Snapshot(
        notes_by_guid={},
        notetypes_by_name={},
        filtered_by_name={},
        deck_paths=set(),
        media_by_filename={},
        warnings=warnings,
        rev_spec=rev_spec,
        root_deck=root_deck,
        gitify_exported_at=None,
    )


def _convert_repo(
    repo: LoadedRepo,
    rev_spec: RevSpec,
    rev_label: Literal["a", "b"],
    warnings: list[WarningEntry],
) -> _Snapshot:
    nt_by_slug = {nt.slug: nt for nt in repo.notetypes}
    notetypes_by_name = {nt.name: _convert_notetype(nt) for nt in repo.notetypes}

    overrides_by_guid: dict[str, list] = {}
    for ov in repo.card_overrides:
        overrides_by_guid.setdefault(ov.note_guid, []).append(ov)

    notes_by_guid: dict[str, NoteSnapshot] = {}
    unknown_refs: dict[str, list[str]] = {}
    for note in repo.notes:
        nt = nt_by_slug.get(note.notetype_slug)
        if nt is None:
            unknown_refs.setdefault(note.notetype_slug, []).append(note.guid)
            continue
        notes_by_guid[note.guid] = _convert_note(note, nt, overrides_by_guid.get(note.guid, []))

    for nt_slug, guids in unknown_refs.items():
        warnings.append(
            WarningEntry(
                kind="unknown_notetype_reference",
                message=(
                    f"rev_{rev_label}: {len(guids)} note(s) reference notetype "
                    f"slug {nt_slug!r} which is not present"
                ),
                details={
                    "rev": rev_label,
                    "notetype_slug": nt_slug,
                    "note_guids": sorted(guids),
                },
            )
        )

    filtered_by_name = {
        fd.name: FilteredDeckSnapshot(
            name=fd.name,
            resched=fd.resched,
            delays=list(fd.delays) if fd.delays is not None else None,
            terms=[
                FilteredDeckTermSnapshot(search=t.search, limit=t.limit, order=t.order)
                for t in fd.terms
            ],
        )
        for fd in repo.filtered.filtered_decks
    }

    deck_paths = set(repo.deck_tree.full_paths)

    media_by_filename = {
        p.name: MediaEntry(
            filename=p.name,
            size=p.stat().st_size,
            content_hash=_hash_file(p),
        )
        for p in repo.media_files
    }

    return _Snapshot(
        notes_by_guid=notes_by_guid,
        notetypes_by_name=notetypes_by_name,
        filtered_by_name=filtered_by_name,
        deck_paths=deck_paths,
        media_by_filename=media_by_filename,
        warnings=warnings,
        rev_spec=rev_spec,
        root_deck=str(repo.gitify.get("root_deck", "")),
        gitify_exported_at=str(repo.gitify.get("exported_at", "")) or None,
    )


def _convert_note(note, nt, overrides) -> NoteSnapshot:
    field_pairs = [
        NoteFieldSnapshot(name=fn, value=v)
        for fn, v in zip(nt.field_names, note.fields)
    ]
    # Pad with empty fields if the CSV row was shorter than the notetype's
    # field list (we don't expect this, but the loader doesn't enforce equal
    # lengths so be defensive at the snapshot layer).
    if len(field_pairs) < len(nt.field_names):
        for fn in nt.field_names[len(field_pairs):]:
            field_pairs.append(NoteFieldSnapshot(name=fn, value=""))
    sort_idx = nt.sort_field_index if 0 <= nt.sort_field_index < len(field_pairs) else 0
    label = _make_label(field_pairs, sort_idx)
    card_overrides = [
        CardOverrideSnapshot(ord=ov.ord, deck_path=ov.deck_path)
        for ov in sorted(overrides, key=lambda o: o.ord)
    ]
    return NoteSnapshot(
        guid=note.guid,
        label=label,
        deck_path=note.deck_path,
        notetype_name=nt.name,
        notetype_slug=nt.slug,
        tags=sorted(note.tags),
        fields=field_pairs,
        card_overrides=card_overrides,
    )


def _convert_notetype(nt) -> NotetypeSnapshot:
    return NotetypeSnapshot(
        name=nt.name,
        slug=nt.slug,
        kind=nt.kind,
        sort_field_index=nt.sort_field_index,
        fields=[
            NotetypeFieldSnapshot(
                name=f.name,
                font=f.font,
                size=f.size,
                sticky=f.sticky,
                rtl=f.rtl,
                plain_text=f.plain_text,
                description=f.description,
            )
            for f in nt.fields
        ],
        templates=[
            NotetypeTemplateSnapshot(
                name=t.name,
                qfmt=t.qfmt,
                afmt=t.afmt,
                bqfmt=t.bqfmt or "",
                bafmt=t.bafmt or "",
            )
            for t in nt.templates
        ],
        css=nt.css,
        latex_pre=nt.latex_pre,
        latex_post=nt.latex_post,
    )


_HTML_TAG = re.compile(r"<[^>]+>")
_LABEL_MAX = 80


def _make_label(fields: list[NoteFieldSnapshot], sort_idx: int) -> str:
    """Sort-field-first label, joined with up to two other non-empty fields."""
    if not fields:
        return ""
    sort_val = _strip_html(fields[sort_idx].value)
    others = [
        _strip_html(f.value)
        for i, f in enumerate(fields)
        if i != sort_idx and _strip_html(f.value)
    ][:2]
    parts = [sort_val] + others
    parts = [p for p in parts if p]
    if not parts:
        return ""
    label = "  /  ".join(parts)
    if len(label) > _LABEL_MAX:
        label = label[: _LABEL_MAX - 3] + "..."
    return label


def _strip_html(s: str) -> str:
    return _HTML_TAG.sub("", s).strip()


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


# ---------- Orchestration ----------


def run_diff(
    rev_a: RevInput,
    rev_b: RevInput,
    *,
    repo_path: Path | None = None,
    cwd: Path | None = None,
    output_format: Literal["json", "text"] = "text",
    color: bool = False,
    abbrev: bool = False,
    compact: bool = False,
) -> tuple[DiffEnvelope, str]:
    """Run the diff and return (envelope, rendered).

    The envelope is the canonical structured result; `rendered` is its
    serialization in the requested format. Callers wanting both formats can
    call `run_diff` once with one format then call the renderer directly.
    """
    # When `--repo` is passed we trust it; otherwise walk up from CWD until
    # we find a gitify.yml. Missing-in-one-rev cases are surfaced as
    # `missing_gitify_yml` warnings inside `_build_snapshot`.
    repo = repo_path.resolve() if repo_path else find_gitified_repo(cwd or Path.cwd())

    with materialize_rev(repo, rev_a) as (path_a, spec_a):
        snap_a = _build_snapshot(path_a, spec_a, "a")
    with materialize_rev(repo, rev_b) as (path_b, spec_b):
        snap_b = _build_snapshot(path_b, spec_b, "b")

    warnings = list(snap_a.warnings) + list(snap_b.warnings)
    _maybe_emit_dirty_wt_warning(snap_a, snap_b, warnings)

    notes_added, notes_removed, notes_changed = diff_notes(
        snap_a.notes_by_guid, snap_b.notes_by_guid
    )
    nt_added, nt_removed, nt_changed = diff_notetypes(
        snap_a.notetypes_by_name, snap_b.notetypes_by_name
    )
    fd_added, fd_removed, fd_changed = diff_filtered_decks(
        snap_a.filtered_by_name, snap_b.filtered_by_name
    )
    deck_added, deck_removed = diff_deck_tree(snap_a.deck_paths, snap_b.deck_paths)
    media_added, media_removed = diff_media(
        snap_a.media_by_filename, snap_b.media_by_filename
    )

    envelope = DiffEnvelope(
        schema_version=DIFF_SCHEMA_VERSION,
        tool_version=__version__,
        generated_at=_iso_now(),
        source=DiffSource(
            repo_path=str(repo),
            root_deck=snap_a.root_deck or snap_b.root_deck,
        ),
        rev_a=snap_a.rev_spec,
        rev_b=snap_b.rev_spec,
        summary=DiffSummary(
            notes=CategorySummary(
                added=len(notes_added),
                removed=len(notes_removed),
                changed=len(notes_changed),
            ),
            notetypes=CategorySummary(
                added=len(nt_added),
                removed=len(nt_removed),
                changed=len(nt_changed),
            ),
            filtered_decks=CategorySummary(
                added=len(fd_added),
                removed=len(fd_removed),
                changed=len(fd_changed),
            ),
            decks=TwoStateSummary(added=len(deck_added), removed=len(deck_removed)),
            media=TwoStateSummary(added=len(media_added), removed=len(media_removed)),
        ),
        warnings=warnings,
        notes=NoteSection(added=notes_added, removed=notes_removed, changed=notes_changed),
        notetypes=NotetypeSection(added=nt_added, removed=nt_removed, changed=nt_changed),
        filtered_decks=FilteredDeckSection(
            added=fd_added, removed=fd_removed, changed=fd_changed
        ),
        deck_tree=DeckTreeSection(added=deck_added, removed=deck_removed),
        media=MediaSection(added=media_added, removed=media_removed),
    )

    if output_format == "json":
        rendered = json_renderer.render(envelope, compact=compact)
    else:
        rendered = text_renderer.render(envelope, color=color, abbrev=abbrev)
    return envelope, rendered


def _maybe_emit_dirty_wt_warning(
    snap_a: _Snapshot, snap_b: _Snapshot, warnings: list[WarningEntry]
) -> None:
    """Warn if rev_a is a commit and rev_b is the working tree with a newer exported_at.

    Indicates the user re-exported but didn't commit — a likely footgun before
    pushing.
    """
    if not isinstance(snap_a.rev_spec, RevRef):
        return
    if not isinstance(snap_b.rev_spec, RevWorkingTree):
        return
    a_ts = snap_a.gitify_exported_at
    b_ts = snap_b.gitify_exported_at
    if not a_ts or not b_ts:
        return
    if b_ts > a_ts:
        warnings.append(
            WarningEntry(
                kind="working_tree_dirty_gitify_yml",
                message=(
                    f"working tree's gitify.yml.exported_at ({b_ts}) is newer than "
                    f"rev_a's ({a_ts}); a re-export may not have been committed yet"
                ),
                details={
                    "working_tree_exported_at": b_ts,
                    "head_exported_at": a_ts,
                },
            )
        )


def _iso_now() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
