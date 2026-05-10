"""Parse a gitified directory back into in-memory schema objects."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from .._yaml import load_yaml
from ..schema import FilteredDecksFile


@dataclass
class LoadedTemplate:
    name: str
    ordinal: int
    qfmt: str
    afmt: str
    bqfmt: str | None = None
    bafmt: str | None = None


@dataclass
class LoadedField:
    name: str
    font: str = "Arial"
    size: int = 20
    sticky: bool = False
    rtl: bool = False
    plain_text: bool = False
    description: str = ""


@dataclass
class LoadedNoteType:
    slug: str
    name: str
    kind: str  # "normal" | "cloze"
    sort_field_index: int
    latex_pre: str
    latex_post: str
    fields: list[LoadedField]
    css: str
    templates: list[LoadedTemplate]

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]


@dataclass
class LoadedNote:
    notetype_slug: str
    guid: str
    deck_path: str
    tags: list[str]
    fields: list[str]


@dataclass
class LoadedCardOverride:
    note_guid: str
    ord: int
    deck_path: str


@dataclass
class LoadedDeckTree:
    root_name: str  # full path of root deck (from gitify.yml)
    full_paths: list[str] = field(default_factory=list)


@dataclass
class LoadedRepo:
    in_dir: Path
    gitify: dict
    notetypes: list[LoadedNoteType]
    notes: list[LoadedNote]
    card_overrides: list[LoadedCardOverride]
    deck_tree: LoadedDeckTree
    filtered: FilteredDecksFile
    media_files: list[Path]


_TEMPLATE_DIR = re.compile(r"^(\d+)-(.+)$")


def load(in_dir: Path) -> LoadedRepo:
    gitify = load_yaml(in_dir / "gitify.yml")
    if int(gitify.get("schema_version", -1)) != 1:
        raise ValueError(
            f"Unsupported gitify.yml schema_version: {gitify.get('schema_version')}. "
            "This anki-gitify build only understands version 1."
        )

    notetypes = _load_notetypes(in_dir / "notetypes")
    deck_tree = _load_deck_tree(in_dir, gitify)
    notes = _load_notes(in_dir / "notes", notetypes)
    overrides = _load_card_overrides(in_dir / "cards.csv")
    filtered = _load_filtered(in_dir / "filtered_decks.yml")
    media_files = _load_media(in_dir / "media")

    return LoadedRepo(
        in_dir=in_dir,
        gitify=gitify,
        notetypes=notetypes,
        notes=notes,
        card_overrides=overrides,
        deck_tree=deck_tree,
        filtered=filtered,
        media_files=media_files,
    )


def _load_notetypes(root: Path) -> list[LoadedNoteType]:
    if not root.is_dir():
        return []
    out: list[LoadedNoteType] = []
    for slug_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        meta = load_yaml(slug_dir / "meta.yml")
        fields = load_yaml(slug_dir / "fields.yml")
        css = (slug_dir / "style.css").read_text(encoding="utf-8")

        templates: list[LoadedTemplate] = []
        templates_dir = slug_dir / "templates"
        if templates_dir.is_dir():
            tmpl_dirs = sorted(
                (p for p in templates_dir.iterdir() if p.is_dir()),
                key=lambda p: p.name,
            )
            for t_dir in tmpl_dirs:
                m = _TEMPLATE_DIR.match(t_dir.name)
                if not m:
                    continue
                ord_idx = int(m.group(1))
                tmeta = load_yaml(t_dir / "meta.yml")
                qfmt = (t_dir / "front.html").read_text(encoding="utf-8")
                afmt = (t_dir / "back.html").read_text(encoding="utf-8")
                bqfmt = None
                bafmt = None
                bq = t_dir / "browser_front.html"
                ba = t_dir / "browser_back.html"
                if bq.is_file():
                    bqfmt = bq.read_text(encoding="utf-8")
                if ba.is_file():
                    bafmt = ba.read_text(encoding="utf-8")
                templates.append(
                    LoadedTemplate(
                        name=tmeta["name"],
                        ordinal=ord_idx,
                        qfmt=qfmt,
                        afmt=afmt,
                        bqfmt=bqfmt,
                        bafmt=bafmt,
                    )
                )
        templates.sort(key=lambda t: t.ordinal)

        loaded_fields = [
            LoadedField(
                name=f["name"],
                font=f.get("font", "Arial"),
                size=int(f.get("size", 20)),
                sticky=bool(f.get("sticky", False)),
                rtl=bool(f.get("rtl", False)),
                plain_text=bool(f.get("plain_text", False)),
                description=f.get("description", "") or "",
            )
            for f in fields
        ]
        out.append(
            LoadedNoteType(
                slug=slug_dir.name,
                name=meta["name"],
                kind=meta["kind"],
                sort_field_index=int(meta.get("sort_field_index", 0)),
                latex_pre=meta.get("latex_pre", "") or "",
                latex_post=meta.get("latex_post", "") or "",
                fields=loaded_fields,
                css=css,
                templates=templates,
            )
        )
    return out


def _load_notes(notes_dir: Path, notetypes: list[LoadedNoteType]) -> list[LoadedNote]:
    if not notes_dir.is_dir():
        return []
    by_slug = {nt.slug: nt for nt in notetypes}
    out: list[LoadedNote] = []
    for csv_path in sorted(notes_dir.glob("*.csv")):
        slug = csv_path.stem
        nt = by_slug.get(slug)
        if nt is None:
            raise ValueError(f"notes/{csv_path.name} has no matching notetype dir")
        with csv_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if header is None:
                continue
            expected = ["guid", "deck_path", "tags"] + nt.field_names
            if header != expected:
                raise ValueError(
                    f"{csv_path}: header {header!r} does not match expected {expected!r}"
                )
            for row in reader:
                if not row:
                    continue
                guid = row[0]
                deck_path = row[1]
                tags = row[2].split()
                fields = row[3:]
                out.append(
                    LoadedNote(
                        notetype_slug=slug,
                        guid=guid,
                        deck_path=deck_path,
                        tags=tags,
                        fields=fields,
                    )
                )
    return out


def _load_card_overrides(path: Path) -> list[LoadedCardOverride]:
    if not path.is_file():
        return []
    out: list[LoadedCardOverride] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header != ["note_guid", "ord", "deck_path"]:
            raise ValueError(f"{path}: unexpected header {header!r}")
        for row in reader:
            if not row:
                continue
            out.append(LoadedCardOverride(note_guid=row[0], ord=int(row[1]), deck_path=row[2]))
    return out


def _load_filtered(path: Path) -> FilteredDecksFile:
    if not path.is_file():
        return FilteredDecksFile()
    data = load_yaml(path)
    return FilteredDecksFile.model_validate(data)


def _load_media(media_dir: Path) -> list[Path]:
    if not media_dir.is_dir():
        return []
    return sorted(p for p in media_dir.iterdir() if p.is_file())


def _load_deck_tree(in_dir: Path, gitify: dict) -> LoadedDeckTree:
    """Walk decks/ recursively to collect every full deck path."""
    root_name = gitify["root_deck"]
    full_paths: list[str] = [root_name]

    def _walk(dir_path: Path, prefix: str) -> None:
        decks_sub = dir_path / "decks"
        if not decks_sub.is_dir():
            return
        for sub in sorted(p for p in decks_sub.iterdir() if p.is_dir()):
            deck_yml = sub / "deck.yml"
            if not deck_yml.is_file():
                continue
            meta = load_yaml(deck_yml)
            full = f"{prefix}::{meta['name']}"
            full_paths.append(full)
            _walk(sub, full)

    _walk(in_dir, root_name)
    return LoadedDeckTree(root_name=root_name, full_paths=full_paths)
