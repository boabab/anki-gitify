"""Copy referenced media into the gitified directory's media/ folder."""

from __future__ import annotations

import shutil
import unicodedata
from pathlib import Path

from ..media_refs import extract_refs


def collect_referenced_media(col, note_ids: list[int], notetype_mids: list[int]) -> set[str]:
    """Scan all in-scope notes' fields and notetype templates for media filenames."""
    refs: set[str] = set()
    for nid in note_ids:
        note = col.get_note(nid)
        for field in note.fields:
            refs |= extract_refs(field)
    for mid in notetype_mids:
        model = col.models.get(mid)
        if model is None:
            continue
        for tmpl in model["tmpls"]:
            refs |= extract_refs(tmpl.get("qfmt", ""))
            refs |= extract_refs(tmpl.get("afmt", ""))
            refs |= extract_refs(tmpl.get("bqfmt", ""))
            refs |= extract_refs(tmpl.get("bafmt", ""))
    return refs


def copy_media(refs: set[str], media_src_dir: Path, out_dir: Path) -> tuple[int, list[str]]:
    """Copy referenced media files. Returns (copied_count, missing_filenames)."""
    if not refs:
        return 0, []
    out = out_dir / "media"
    out.mkdir(parents=True, exist_ok=True)
    copied = 0
    missing: list[str] = []
    for ref in sorted(refs):
        nfc = unicodedata.normalize("NFC", ref)
        candidates = [media_src_dir / nfc, media_src_dir / ref]
        # macOS APFS commonly stores filenames as NFD; try both spellings.
        nfd = unicodedata.normalize("NFD", ref)
        if nfd != ref:
            candidates.append(media_src_dir / nfd)
        src = next((c for c in candidates if c.is_file()), None)
        if src is None:
            missing.append(ref)
            continue
        shutil.copyfile(src, out / nfc)
        copied += 1
    return copied, missing
