"""Emit filtered_decks.yml + the human-readable FILTERED_DECKS.md mirror."""

from __future__ import annotations

from pathlib import Path

from .._yaml import dump_yaml
from ..schema import ORDER_NAMES, SCHEMA_VERSION
from .decks import DeckNode


def _filtered_to_dict(node: DeckNode, deck_dict: dict) -> dict:
    """Map an Anki filtered-deck legacy dict to our serialization shape."""
    terms_raw = deck_dict.get("terms") or []
    terms: list[dict] = []
    for entry in terms_raw:
        # Anki legacy shape: [search:str, limit:int, order:int]
        search, limit, order = entry[0], int(entry[1]), int(entry[2])
        terms.append({"search": search, "limit": limit, "order": order})
    return {
        "name": node.full_path,
        "resched": bool(deck_dict.get("resched", True)),
        "delays": deck_dict.get("delays"),
        "terms": terms,
    }


def emit_filtered(col, filtered_nodes: list[DeckNode], out_dir: Path) -> int:
    """Write `filtered_decks.yml` (always) and `FILTERED_DECKS.md` (only if non-empty).

    Returns count of filtered decks emitted.
    """
    payload = {"schema_version": SCHEMA_VERSION, "filtered_decks": []}
    for node in filtered_nodes:
        deck = col.decks.get(node.did)
        payload["filtered_decks"].append(_filtered_to_dict(node, deck))
    payload["filtered_decks"].sort(key=lambda d: d["name"])

    dump_yaml(payload, out_dir / "filtered_decks.yml")

    md_path = out_dir / "FILTERED_DECKS.md"
    if not payload["filtered_decks"]:
        # ensure no stale md from a previous export with filtered decks
        if md_path.exists():
            md_path.unlink()
        return 0

    md = render_filtered_md(payload["filtered_decks"])
    md_path.write_text(md, encoding="utf-8", newline="\n")
    return len(payload["filtered_decks"])


def render_filtered_md(decks: list[dict]) -> str:
    """Deterministic markdown render. Used both at export and by `verify`."""
    lines = [
        "# Filtered decks",
        "",
        "> Auto-generated from `filtered_decks.yml`. Do not edit by hand — edit the YAML.",
        "",
        "After importing this deck, recreate these filtered decks via Tools → Create Filtered Deck "
        "(or `anki-gitify apply-filtered` once v2 ships).",
        "",
    ]
    for deck in decks:
        lines.append(f"## {deck['name']}")
        for i, term in enumerate(deck["terms"], 1):
            suffix = f" (search {i})" if len(deck["terms"]) > 1 else ""
            order_name = ORDER_NAMES.get(term["order"], "unknown order")
            lines.append(f"- **Search**{suffix}: `{term['search']}`")
            lines.append(f"- **Limit**{suffix}: {term['limit']}")
            lines.append(f"- **Order**{suffix}: {term['order']} ({order_name})")
        lines.append(f"- **Reschedule**: {'yes' if deck['resched'] else 'no'}")
        if deck.get("delays"):
            lines.append(f"- **Delays**: {deck['delays']}")
        lines.append("")
    return "\n".join(lines)
