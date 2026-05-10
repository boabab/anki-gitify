"""Stable, deterministic IDs for genanki Models/Decks derived from names."""

from __future__ import annotations

import hashlib


_MASK_63 = (1 << 63) - 1


def _hash63(name: str) -> int:
    """SHA1(name) → positive 63-bit int. Wide enough that collision with
    Anki's epoch-millisecond IDs (~41 bits) is vanishingly unlikely."""
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & _MASK_63


def model_id_for(name: str) -> int:
    return _hash63(f"notetype:{name}")


def deck_id_for(full_path: str) -> int:
    return _hash63(f"deck:{full_path}")
