"""Walk a deck subtree and emit `decks/<slug>/deck.yml` per node."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .._yaml import dump_yaml
from ..naming import Slugger


@dataclass
class DeckNode:
    did: int
    name: str  # last path component
    full_path: str
    description: str
    is_filtered: bool
    children: list["DeckNode"] = field(default_factory=list)


def build_tree(col, root_did: int) -> DeckNode:
    """Build a `DeckNode` tree rooted at `root_did` from the live collection."""

    def _node(did: int) -> DeckNode:
        deck = col.decks.get(did)
        full = deck["name"]  # full path with `::`
        last = full.rsplit("::", 1)[-1]
        return DeckNode(
            did=did,
            name=last,
            full_path=full,
            description=deck.get("desc", "") or "",
            is_filtered=bool(deck.get("dyn", 0)),
            children=[],
        )

    root = _node(root_did)
    by_id: dict[int, DeckNode] = {root_did: root}

    # col.decks.children(did) returns immediate children as [(name, id), ...]
    # but children-of-children require recursion; do it by walking all decks
    # under the root prefix.
    root_prefix = root.full_path + "::"
    for entry in col.decks.all_names_and_ids():
        name = entry.name
        did = entry.id
        if did == root_did:
            continue
        if not (name == root.full_path or name.startswith(root_prefix)):
            continue
        if did not in by_id:
            by_id[did] = _node(did)

    # link children based on full_path
    for node in by_id.values():
        if node is root:
            continue
        parent_path = node.full_path.rsplit("::", 1)[0]
        parent = next((n for n in by_id.values() if n.full_path == parent_path), None)
        if parent is None:
            # an orphan (shouldn't happen given prefix filter)
            parent = root
        parent.children.append(node)

    # deterministic order
    def _sort(n: DeckNode) -> None:
        n.children.sort(key=lambda c: c.name)
        for c in n.children:
            _sort(c)

    _sort(root)
    return root


def collect_normal_paths(root: DeckNode) -> list[str]:
    """Return full paths of every non-filtered deck in the tree, in stable order."""
    out: list[str] = []

    def visit(n: DeckNode) -> None:
        if not n.is_filtered:
            out.append(n.full_path)
        for c in n.children:
            visit(c)

    visit(root)
    return sorted(out)


def collect_normal_ids(root: DeckNode) -> list[int]:
    out: list[int] = []

    def visit(n: DeckNode) -> None:
        if not n.is_filtered:
            out.append(n.did)
        for c in n.children:
            visit(c)

    visit(root)
    return out


def collect_filtered_nodes(root: DeckNode) -> list[DeckNode]:
    out: list[DeckNode] = []

    def visit(n: DeckNode) -> None:
        if n.is_filtered:
            out.append(n)
        for c in n.children:
            visit(c)

    visit(root)
    out.sort(key=lambda n: n.full_path)
    return out


def deck_path_by_id(root: DeckNode) -> dict[int, str]:
    """Map every deck id (normal + filtered) under root to its full path."""
    out: dict[int, str] = {}

    def visit(n: DeckNode) -> None:
        out[n.did] = n.full_path
        for c in n.children:
            visit(c)

    visit(root)
    return out


def emit_deck_tree(root: DeckNode, out_dir: Path) -> None:
    """Write `deck.yml` for the root and `decks/<slug>/` for each non-filtered child."""
    slugger = Slugger()
    _write_deck_node(root, out_dir, slugger, is_root=True)


def _write_deck_node(node: DeckNode, dir_path: Path, slugger: Slugger, *, is_root: bool) -> None:
    if node.is_filtered:
        return
    dir_path.mkdir(parents=True, exist_ok=True)
    dump_yaml(
        {"name": node.name, "description": node.description},
        dir_path / "deck.yml",
    )
    children = [c for c in node.children if not c.is_filtered]
    if not children:
        return
    decks_dir = dir_path / "decks"
    decks_dir.mkdir(exist_ok=True)
    # use a per-parent slugger so siblings don't collide
    child_slugger = Slugger()
    for child in sorted(children, key=lambda c: c.name):
        slug = child_slugger.slug(child.name)
        _write_deck_node(child, decks_dir / slug, child_slugger, is_root=False)
