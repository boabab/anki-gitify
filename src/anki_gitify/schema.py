"""Pydantic models for the on-disk gitified format.

This is the single shared contract between the export and import halves.
The format on disk is the API; if you change a model here without bumping
SCHEMA_VERSION you will silently break repos in the wild.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GitifyMeta(_Strict):
    """Top of `gitify.yml` — describes the export."""

    schema_version: int = SCHEMA_VERSION
    tool_version: str
    source_profile: str
    source_collection: str
    exported_at: str
    anki_module_version: str
    root_deck: str
    counts: dict[str, int] = Field(default_factory=dict)


class DeckMeta(_Strict):
    """`deck.yml` for a single (normal) deck node in the tree."""

    name: str
    description: str = ""


class FieldDef(_Strict):
    name: str
    font: str = "Arial"
    size: int = 20
    sticky: bool = False
    rtl: bool = False
    plain_text: bool = False
    description: str = ""


class TemplateMeta(_Strict):
    """`templates/NN-<slug>/meta.yml`."""

    name: str
    ordinal: int


class NoteTypeMeta(_Strict):
    """`notetypes/<slug>/meta.yml`."""

    name: str
    kind: Literal["normal", "cloze"]
    sort_field_index: int = 0
    latex_pre: str = ""
    latex_post: str = ""


class FilteredDeckTerm(_Strict):
    search: str
    limit: int
    order: int


class FilteredDeck(_Strict):
    name: str
    resched: bool
    delays: list[int] | None = None
    terms: list[FilteredDeckTerm]


class FilteredDecksFile(_Strict):
    """`filtered_decks.yml` — top-level wrapper."""

    schema_version: int = SCHEMA_VERSION
    filtered_decks: list[FilteredDeck] = Field(default_factory=list)


# Human-readable order names for FILTERED_DECKS.md rendering.
# Mirrors Anki's FilteredDeckTerms.order enum (rslib/proto/anki/decks.proto).
ORDER_NAMES: dict[int, str] = {
    0: "oldest seen first",
    1: "random",
    2: "most lapses first",
    3: "added order",
    4: "due date",
    5: "most retrievable",
    6: "reverse added order",
    7: "lowest interval first",
    8: "highest interval first",
    9: "lowest ease first",
    10: "highest ease first",
}
