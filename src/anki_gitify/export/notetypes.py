"""Serialize Anki notetypes (models) to the gitified directory layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .._yaml import dump_yaml
from ..naming import Slugger


@dataclass(frozen=True)
class NoteTypeRef:
    mid: int
    name: str
    fields: list[str]  # field names, in order
    sort_field_index: int
    is_cloze: bool


def emit_notetypes(col, mids: list[int], out_dir: Path) -> tuple[dict[int, str], dict[int, NoteTypeRef]]:
    """Write `notetypes/<slug>/...` for each model id.

    Returns:
        - mid → notetype slug (used by export/notes.py to pick CSV filename)
        - mid → NoteTypeRef (used by export/notes.py for headers)
    """
    base = out_dir / "notetypes"
    base.mkdir(parents=True, exist_ok=True)

    slugger = Slugger()
    slug_by_mid: dict[int, str] = {}
    ref_by_mid: dict[int, NoteTypeRef] = {}

    # Sort by name for deterministic slug assignment.
    models = [col.models.get(mid) for mid in mids]
    models = [m for m in models if m is not None]
    models.sort(key=lambda m: m["name"])

    for model in models:
        name = model["name"]
        slug = slugger.slug(name)
        slug_by_mid[model["id"]] = slug

        nt_dir = base / slug
        nt_dir.mkdir(parents=True, exist_ok=True)

        is_cloze = int(model.get("type", 0)) == 1
        meta = {
            "name": name,
            "kind": "cloze" if is_cloze else "normal",
            "sort_field_index": int(model.get("sortf", 0)),
            "latex_pre": model.get("latexPre", "") or "",
            "latex_post": model.get("latexPost", "") or "",
        }
        dump_yaml(meta, nt_dir / "meta.yml")

        fields = [
            {
                "name": f["name"],
                "font": f.get("font", "Arial"),
                "size": int(f.get("size", 20)),
                "sticky": bool(f.get("sticky", False)),
                "rtl": bool(f.get("rtl", False)),
                "plain_text": bool(f.get("plainText", False)),
                "description": f.get("description", "") or "",
            }
            for f in model["flds"]
        ]
        dump_yaml(fields, nt_dir / "fields.yml")

        css = model.get("css", "") or ""
        (nt_dir / "style.css").write_text(css, encoding="utf-8", newline="\n")

        templates_dir = nt_dir / "templates"
        templates_dir.mkdir(exist_ok=True)
        tmpl_slugger = Slugger()
        for ord_idx, tmpl in enumerate(model["tmpls"]):
            tname = tmpl["name"]
            tslug = tmpl_slugger.slug(tname)
            t_dir = templates_dir / f"{ord_idx:02d}-{tslug}"
            t_dir.mkdir(parents=True, exist_ok=True)
            dump_yaml({"name": tname, "ordinal": ord_idx}, t_dir / "meta.yml")
            qfmt = tmpl.get("qfmt", "") or ""
            afmt = tmpl.get("afmt", "") or ""
            (t_dir / "front.html").write_text(qfmt, encoding="utf-8", newline="\n")
            (t_dir / "back.html").write_text(afmt, encoding="utf-8", newline="\n")
            bqfmt = tmpl.get("bqfmt", "") or ""
            bafmt = tmpl.get("bafmt", "") or ""
            if bqfmt and bqfmt != qfmt:
                (t_dir / "browser_front.html").write_text(bqfmt, encoding="utf-8", newline="\n")
            if bafmt and bafmt != afmt:
                (t_dir / "browser_back.html").write_text(bafmt, encoding="utf-8", newline="\n")

        ref_by_mid[model["id"]] = NoteTypeRef(
            mid=model["id"],
            name=name,
            fields=[f["name"] for f in model["flds"]],
            sort_field_index=int(model.get("sortf", 0)),
            is_cloze=is_cloze,
        )

    return slug_by_mid, ref_by_mid
