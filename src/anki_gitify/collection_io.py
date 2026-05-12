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
        msg = str(exc).lower()
        if (
            "locked" in msg
            or "database is locked" in msg
            or "already open" in msg
            or "currently syncing" in msg
        ):
            raise RuntimeError(
                f"Cannot open {path}: file is locked. "
                "Close Anki (and wait for any in-progress sync to finish) "
                "before running anki-gitify."
            ) from exc
        raise
    try:
        yield col
    finally:
        col.close(downgrade=False)
