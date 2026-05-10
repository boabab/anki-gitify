"""Slugify names to filesystem-safe directory components, with collision tracking."""

from __future__ import annotations

import re
import unicodedata


_SLUG_PUNCT = re.compile(r"[^a-z0-9]+")


def _basic_slug(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    s = _SLUG_PUNCT.sub("-", ascii_only.lower()).strip("-")
    return s or "unnamed"


class Slugger:
    """Generates collision-free slugs and remembers prior assignments.

    Two distinct names that slugify to the same string get suffixed `-2`, `-3`, etc.
    Order matters: feed names in a deterministic order (sorted) so that across
    runs the same name always gets the same slug.
    """

    def __init__(self) -> None:
        self._used: set[str] = set()
        self._by_name: dict[str, str] = {}

    def slug(self, name: str) -> str:
        if name in self._by_name:
            return self._by_name[name]
        base = _basic_slug(name)
        candidate = base
        i = 2
        while candidate in self._used:
            candidate = f"{base}-{i}"
            i += 1
        self._used.add(candidate)
        self._by_name[name] = candidate
        return candidate
