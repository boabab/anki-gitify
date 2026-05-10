"""Open an Anki collection through the official Python API."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def open_collection(path: Path) -> Iterator:
    """Yield an `anki.collection.Collection` and close it on exit.

    Raises a clear error if the collection is locked (Anki is open).
    """
    from anki.collection import Collection

    try:
        col = Collection(str(path))
    except Exception as exc:
        msg = str(exc)
        if "locked" in msg.lower() or "database is locked" in msg.lower():
            raise RuntimeError(
                f"Cannot open {path}: file is locked. "
                "Close Anki before running anki-gitify."
            ) from exc
        raise
    try:
        yield col
    finally:
        col.close(downgrade=False)
