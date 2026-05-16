"""Pydantic schema for the `anki-gitify diff` JSON contract.

This is independent of the on-disk gitified-format `SCHEMA_VERSION` in
[`schema.py`](../schema.py) — diff envelope versioning is governed by
`DIFF_SCHEMA_VERSION` below. See [`docs/DESIGN.md`](../../../docs/DESIGN.md)
§"Semantic diff" for the bump-rules.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


DIFF_SCHEMA_VERSION = 1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- Snapshot leaves ----------


class NoteFieldSnapshot(_Strict):
    name: str
    value: str


class CardOverrideSnapshot(_Strict):
    ord: int
    deck_path: str


class NoteSnapshot(_Strict):
    guid: str
    label: str
    deck_path: str
    notetype_name: str
    notetype_slug: str
    tags: list[str]
    fields: list[NoteFieldSnapshot]
    card_overrides: list[CardOverrideSnapshot] = Field(default_factory=list)


class NotetypeFieldSnapshot(_Strict):
    name: str
    font: str = "Arial"
    size: int = 20
    sticky: bool = False
    rtl: bool = False
    plain_text: bool = False
    description: str = ""


class NotetypeTemplateSnapshot(_Strict):
    name: str
    qfmt: str
    afmt: str
    bqfmt: str = ""
    bafmt: str = ""


class NotetypeSnapshot(_Strict):
    name: str
    slug: str
    kind: Literal["normal", "cloze"]
    sort_field_index: int
    fields: list[NotetypeFieldSnapshot]
    templates: list[NotetypeTemplateSnapshot]
    css: str
    latex_pre: str
    latex_post: str


class FilteredDeckTermSnapshot(_Strict):
    search: str
    limit: int
    order: int


class FilteredDeckSnapshot(_Strict):
    name: str
    resched: bool
    delays: list[int] | None = None
    terms: list[FilteredDeckTermSnapshot]


class MediaEntry(_Strict):
    filename: str
    size: int
    content_hash: str  # "sha256:<hex>"


# ---------- Per-entity change blocks ----------


class TextDelta(_Strict):
    before: str
    after: str
    unified_diff: str


class ScalarChange(_Strict):
    """Generic before/after for primitive values used in changes blocks."""

    before: object
    after: object


class DeckMoveChange(_Strict):
    before: str
    after: str


class NotetypeRefChange(_Strict):
    before: str
    after: str


class NoteFieldChange(_Strict):
    name: str
    before: str
    after: str
    unified_diff: str


class CardOverrideEdge(_Strict):
    deck_path: str


class CardOverrideChange(_Strict):
    ord: int
    before: CardOverrideEdge | None
    after: CardOverrideEdge | None


class NoteChanges(_Strict):
    tags_added: list[str]
    tags_removed: list[str]
    deck_moved: DeckMoveChange | None
    notetype_changed: NotetypeRefChange | None
    fields_changed: list[NoteFieldChange]
    card_overrides_changed: list[CardOverrideChange]


class ChangedNote(_Strict):
    before: NoteSnapshot
    after: NoteSnapshot
    changes: NoteChanges


class NotetypeFieldPropsDelta(_Strict):
    """Subset of field properties that changed; values mirror NotetypeFieldSnapshot."""

    font: str | None = None
    size: int | None = None
    sticky: bool | None = None
    rtl: bool | None = None
    plain_text: bool | None = None
    description: str | None = None


class NotetypeFieldChange(_Strict):
    status: Literal["added", "removed", "changed"]
    name: str
    index: int | None = None
    font: str | None = None
    size: int | None = None
    sticky: bool | None = None
    rtl: bool | None = None
    plain_text: bool | None = None
    description: str | None = None
    before: NotetypeFieldPropsDelta | None = None
    after: NotetypeFieldPropsDelta | None = None


class NotetypeTemplateChange(_Strict):
    name: str
    qfmt: TextDelta | None
    afmt: TextDelta | None
    bqfmt: TextDelta | None
    bafmt: TextDelta | None


class FieldOrderChange(_Strict):
    before: list[str]
    after: list[str]


class NotetypeChanges(_Strict):
    sort_field_index_changed: ScalarChange | None
    fields_changed: list[NotetypeFieldChange]
    field_order_changed: FieldOrderChange | None
    templates_changed: list[NotetypeTemplateChange]
    css_changed: TextDelta | None
    latex_pre_changed: TextDelta | None
    latex_post_changed: TextDelta | None


class ChangedNotetype(_Strict):
    before: NotetypeSnapshot
    after: NotetypeSnapshot
    changes: NotetypeChanges


class FilteredDeckChanges(_Strict):
    search_changed: ScalarChange | None
    limit_changed: ScalarChange | None
    order_changed: ScalarChange | None
    resched_changed: ScalarChange | None
    delays_changed: ScalarChange | None


class ChangedFilteredDeck(_Strict):
    before: FilteredDeckSnapshot
    after: FilteredDeckSnapshot
    changes: FilteredDeckChanges


# ---------- Top-level sections ----------


class NoteSection(_Strict):
    added: list[NoteSnapshot] = Field(default_factory=list)
    removed: list[NoteSnapshot] = Field(default_factory=list)
    changed: list[ChangedNote] = Field(default_factory=list)


class NotetypeSection(_Strict):
    added: list[NotetypeSnapshot] = Field(default_factory=list)
    removed: list[NotetypeSnapshot] = Field(default_factory=list)
    changed: list[ChangedNotetype] = Field(default_factory=list)


class FilteredDeckSection(_Strict):
    added: list[FilteredDeckSnapshot] = Field(default_factory=list)
    removed: list[FilteredDeckSnapshot] = Field(default_factory=list)
    changed: list[ChangedFilteredDeck] = Field(default_factory=list)


class DeckTreeSection(_Strict):
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class MediaSection(_Strict):
    added: list[MediaEntry] = Field(default_factory=list)
    removed: list[MediaEntry] = Field(default_factory=list)


# ---------- Envelope ----------


class CategorySummary(_Strict):
    added: int
    removed: int
    changed: int


class TwoStateSummary(_Strict):
    added: int
    removed: int


class DiffSummary(_Strict):
    notes: CategorySummary
    notetypes: CategorySummary
    filtered_decks: CategorySummary
    decks: TwoStateSummary
    media: TwoStateSummary


class RevRef(_Strict):
    kind: Literal["ref"] = "ref"
    ref: str
    sha: str
    commit_timestamp: str
    commit_subject: str


class RevWorkingTree(_Strict):
    kind: Literal["working_tree"] = "working_tree"


RevSpec = Annotated[Union[RevRef, RevWorkingTree], Field(discriminator="kind")]


class DiffSource(_Strict):
    repo_path: str
    root_deck: str


class WarningEntry(_Strict):
    kind: Literal[
        "schema_mismatch",
        "missing_gitify_yml",
        "unknown_notetype_reference",
        "undecodable_file",
        "working_tree_dirty_gitify_yml",
    ]
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class DiffEnvelope(_Strict):
    schema_version: int
    tool_version: str
    generated_at: str
    source: DiffSource
    rev_a: RevSpec
    rev_b: RevSpec
    summary: DiffSummary
    warnings: list[WarningEntry]
    notes: NoteSection
    notetypes: NotetypeSection
    filtered_decks: FilteredDeckSection
    deck_tree: DeckTreeSection
    media: MediaSection

    def is_empty(self) -> bool:
        s = self.summary
        return (
            s.notes.added == 0
            and s.notes.removed == 0
            and s.notes.changed == 0
            and s.notetypes.added == 0
            and s.notetypes.removed == 0
            and s.notetypes.changed == 0
            and s.filtered_decks.added == 0
            and s.filtered_decks.removed == 0
            and s.filtered_decks.changed == 0
            and s.decks.added == 0
            and s.decks.removed == 0
            and s.media.added == 0
            and s.media.removed == 0
        )
