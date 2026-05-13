"""Semantic diff of two revisions of a gitified Anki repo."""

from .diff import (
    CardOverrideChange,
    DeckDiff,
    DeckTreeDiff,
    FieldChange,
    FilteredDeckChange,
    FilteredDecksDiff,
    MediaDiff,
    MetadataDiff,
    NoteChange,
    NoteRef,
    NoteTypeMigration,
    NotesDiff,
    NotetypeChange,
    NotetypesDiff,
    TemplateChange,
    compute_diff,
)
from .git_io import GitError, materialize_revision, repo_toplevel, resolve_ref
from .render import render_json, render_markdown, render_terminal

__all__ = [
    "CardOverrideChange",
    "DeckDiff",
    "DeckTreeDiff",
    "FieldChange",
    "FilteredDeckChange",
    "FilteredDecksDiff",
    "GitError",
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
    "materialize_revision",
    "render_json",
    "render_markdown",
    "render_terminal",
    "repo_toplevel",
    "resolve_ref",
]
