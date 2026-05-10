"""Build genanki Models/Decks/Notes from a LoadedRepo and write the .apkg."""

from __future__ import annotations

from pathlib import Path

import genanki

from ..fingerprint import deck_id_for, model_id_for
from .loader import LoadedNote, LoadedNoteType, LoadedRepo


def build_models(notetypes: list[LoadedNoteType]) -> dict[str, genanki.Model]:
    out: dict[str, genanki.Model] = {}
    for nt in notetypes:
        templates = [
            {
                "name": t.name,
                "qfmt": t.qfmt,
                "afmt": t.afmt,
                **({"bqfmt": t.bqfmt} if t.bqfmt else {}),
                **({"bafmt": t.bafmt} if t.bafmt else {}),
            }
            for t in nt.templates
        ]
        fields = [
            {
                "name": f.name,
                "font": f.font,
                "size": f.size,
                "sticky": f.sticky,
                "rtl": f.rtl,
                "description": f.description,
            }
            for f in nt.fields
        ]
        model_type = genanki.Model.CLOZE if nt.kind == "cloze" else genanki.Model.FRONT_BACK
        model = genanki.Model(
            model_id=model_id_for(nt.name),
            name=nt.name,
            fields=fields,
            templates=templates,
            css=nt.css,
            model_type=model_type,
            sort_field_index=nt.sort_field_index,
        )
        out[nt.slug] = model
    return out


def build_decks(deck_paths: list[str]) -> dict[str, genanki.Deck]:
    out: dict[str, genanki.Deck] = {}
    for path in sorted(set(deck_paths)):
        out[path] = genanki.Deck(deck_id=deck_id_for(path), name=path)
    return out


def build_package(repo: LoadedRepo, out_apkg: Path) -> None:
    """Build the .apkg from the loaded repo and write to `out_apkg`."""
    models = build_models(repo.notetypes)

    # Decks come from both the explicit tree AND every distinct deck_path
    # appearing in any note row (notetypes can be shared across decks).
    deck_paths = list(repo.deck_tree.full_paths)
    deck_paths.extend(n.deck_path for n in repo.notes)
    decks = build_decks(deck_paths)

    for note in repo.notes:
        model = models.get(note.notetype_slug)
        if model is None:
            raise ValueError(f"Note refers to unknown notetype slug {note.notetype_slug!r}")
        target_deck = decks.get(note.deck_path)
        if target_deck is None:
            target_deck = genanki.Deck(deck_id=deck_id_for(note.deck_path), name=note.deck_path)
            decks[note.deck_path] = target_deck
        gnote = genanki.Note(
            model=model,
            fields=note.fields,
            tags=note.tags,
            guid=note.guid,
        )
        target_deck.add_note(gnote)

    pkg = genanki.Package(list(decks.values()))
    pkg.media_files = [str(p) for p in repo.media_files]
    pkg.write_to_file(str(out_apkg))


def model_for_notetype(notetypes: list[LoadedNoteType], slug: str) -> genanki.Model:
    return build_models(notetypes)[slug]


def note_to_genanki(note: LoadedNote, model: genanki.Model) -> genanki.Note:
    return genanki.Note(model=model, fields=note.fields, tags=note.tags, guid=note.guid)
