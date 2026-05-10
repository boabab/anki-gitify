"""Compute home-deck-per-note and detect divergent placements."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class CardRow:
    cid: int
    nid: int
    did: int
    ord: int
    odid: int

    @property
    def home_did(self) -> int:
        return self.odid if self.odid > 0 else self.did


@dataclass
class NotePlacement:
    nid: int
    home_path: str  # the chosen single deck_path for this note (most-common deck)
    overrides: list[tuple[int, str]]  # (ord, deck_path) for diverging cards


def compute_placements(
    cards: list[CardRow],
    deck_path_by_id: dict[int, str],
) -> tuple[dict[int, NotePlacement], bool]:
    """Bucket cards by note and decide each note's primary `deck_path` + overrides.

    The primary deck is the one holding the most cards (ties broken alphabetically
    by full path for determinism). Diverging cards (different home_did from the
    primary) become entries in `overrides`.

    Returns the placements keyed by nid, plus a bool indicating whether any
    note had divergent home decks (used to decide whether to emit cards.csv).
    """
    by_note: dict[int, list[CardRow]] = defaultdict(list)
    for card in cards:
        by_note[card.nid].append(card)

    placements: dict[int, NotePlacement] = {}
    any_diverge = False
    for nid, group in by_note.items():
        path_counts: Counter[str] = Counter()
        for card in group:
            path = deck_path_by_id[card.home_did]
            path_counts[path] += 1
        # most common; tie-break alphabetically by path (asc)
        primary = sorted(path_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        overrides: list[tuple[int, str]] = []
        for card in sorted(group, key=lambda c: c.ord):
            path = deck_path_by_id[card.home_did]
            if path != primary:
                overrides.append((card.ord, path))
                any_diverge = True
        placements[nid] = NotePlacement(nid=nid, home_path=primary, overrides=overrides)
    return placements, any_diverge
