"""Top-level orchestrator: collection.anki2 → gitified directory."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from .. import __version__
from .._yaml import dump_yaml
from ..collection_io import open_collection
from ..profile import ProfilePaths
from .cards import CardRow, compute_placements
from .decks import (
    build_tree,
    collect_filtered_nodes,
    collect_normal_ids,
    collect_normal_paths,
    deck_path_by_id,
    emit_deck_tree,
)
from .filtered import emit_filtered
from .media import collect_referenced_media, copy_media
from .notes import emit_cards_csv, emit_notes
from .notetypes import emit_notetypes


@dataclass
class ExportReport:
    out_dir: Path
    notetypes: int
    notes: int
    cards: int
    media: int
    media_missing: list[str]
    filtered_decks: int
    has_card_overrides: bool


def export(
    deck_name: str,
    out_dir: Path,
    profile: ProfilePaths,
    *,
    include_media: bool = True,
    force: bool = False,
) -> ExportReport:
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise FileExistsError(
            f"{out_dir} is not empty. Pass --force to overwrite."
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    with open_collection(profile.collection) as col:
        # 3. Resolve target deck and reject filtered roots.
        root_did = col.decks.id_for_name(deck_name)
        if root_did is None:
            available = [e.name for e in col.decks.all_names_and_ids()]
            sample = ", ".join(sorted(available)[:8])
            raise ValueError(
                f"Deck not found: {deck_name!r}. "
                f"Existing decks include: {sample}"
            )
        root_dict = col.decks.get(root_did)
        if int(root_dict.get("dyn", 0)) == 1:
            raise ValueError(
                f"{deck_name!r} is a filtered deck — its cards live in their home decks. "
                "Export the home deck containing those cards instead."
            )

        # 4. Walk subtree.
        root_node = build_tree(col, root_did)
        normal_ids = collect_normal_ids(root_node)
        filtered_nodes = collect_filtered_nodes(root_node)
        path_by_id = deck_path_by_id(root_node)

        # 5. Collect cards by HOME deck.
        if normal_ids:
            placeholders = ",".join("?" for _ in normal_ids)
            sql = (
                f"SELECT id, nid, did, ord, odid FROM cards "
                f"WHERE (CASE WHEN odid > 0 THEN odid ELSE did END) IN ({placeholders})"
            )
            raw_rows = col.db.all(sql, *normal_ids)
        else:
            raw_rows = []
        cards: list[CardRow] = [
            CardRow(cid=int(r[0]), nid=int(r[1]), did=int(r[2]), ord=int(r[3]), odid=int(r[4]))
            for r in raw_rows
        ]
        note_ids = sorted({c.nid for c in cards})

        # 6. Referenced notetypes.
        if note_ids:
            placeholders = ",".join("?" for _ in note_ids)
            mid_rows = col.db.all(
                f"SELECT DISTINCT mid FROM notes WHERE id IN ({placeholders})",
                *note_ids,
            )
            mids = sorted({int(r[0]) for r in mid_rows})
        else:
            mids = []

        # 7. Emit notetypes/.
        slug_by_mid, ref_by_mid = emit_notetypes(col, mids, out_dir)

        # 8. Compute home-deck-per-note.
        placements, has_overrides = compute_placements(cards, path_by_id)

        # 9. Emit notes/.
        nid_to_guid: dict[int, str] = {}
        for nid in note_ids:
            note = col.get_note(nid)
            nid_to_guid[nid] = note.guid
        notes_count = emit_notes(col, note_ids, placements, slug_by_mid, ref_by_mid, out_dir)

        # 10. Emit deck tree.
        emit_deck_tree(root_node, out_dir)

        # 11. Emit filtered_decks.yml + FILTERED_DECKS.md.
        filtered_count = emit_filtered(col, filtered_nodes, out_dir)

        # 12. Emit cards.csv (only if divergent).
        cards_overrides_count = emit_cards_csv(placements, nid_to_guid, out_dir)

        # 13. Emit media/.
        media_count = 0
        media_missing: list[str] = []
        if include_media:
            refs = collect_referenced_media(col, note_ids, mids)
            media_count, media_missing = copy_media(refs, profile.media_dir, out_dir)

        # 14. Emit gitify.yml.
        try:
            from anki import buildinfo as _anki_buildinfo  # type: ignore
            anki_version = getattr(_anki_buildinfo, "version", "unknown")
        except Exception:
            anki_version = "unknown"

        gitify_meta = {
            "schema_version": 1,
            "tool_version": __version__,
            "source_profile": profile.profile,
            "source_collection": profile.collection.name,
            "exported_at": _dt.datetime.now(_dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "anki_module_version": str(anki_version),
            "root_deck": root_node.full_path,
            "counts": {
                "notetypes": len(mids),
                "notes": notes_count,
                "cards": len(cards),
                "media": media_count,
                "filtered_decks": filtered_count,
                "card_overrides": cards_overrides_count,
                "normal_decks": len(collect_normal_paths(root_node)),
            },
        }
        dump_yaml(gitify_meta, out_dir / "gitify.yml")

    return ExportReport(
        out_dir=out_dir,
        notetypes=len(mids),
        notes=notes_count,
        cards=len(cards),
        media=media_count,
        media_missing=media_missing,
        filtered_decks=filtered_count,
        has_card_overrides=has_overrides,
    )
