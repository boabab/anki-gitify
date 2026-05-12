"""Stable public API for embedding ``anki-gitify`` in other tools.

Everything importable from this module is part of the documented surface and
follows SemVer (see ``docs/API.md``). Code that imports from anywhere else in
this package (``anki_gitify.importer.*``, ``anki_gitify.export.*``, etc.) is
relying on internals that are free to change between minor versions.

Stability rules in short:

* Patch (X.Y.Z+1): bug fixes only, no surface change.
* Minor (X.Y+1.0): additive changes — new names, new optional kwargs, new
  fields on returned dataclasses. Existing call patterns keep working.
* Major (X+1.0.0): removals, renames, or changes that break a documented
  call pattern.
"""

from __future__ import annotations

from .importer.apply_filtered import ApplyFilteredReport, apply_filtered
from .importer.importer import CardOverrideError, ImportReport, import_
from .importer.loader import LoadedRepo, load
from .importer.verify import VerifyReport, verify
from .profile import (
    ProfilePaths,
    default_anki_base,
    list_profiles,
    resolve_profile_paths,
)


API_VERSION = (1, 0, 0)

__all__ = [
    "API_VERSION",
    "import_",
    "ImportReport",
    "CardOverrideError",
    "apply_filtered",
    "ApplyFilteredReport",
    "verify",
    "VerifyReport",
    "load",
    "LoadedRepo",
    "list_profiles",
    "resolve_profile_paths",
    "default_anki_base",
    "ProfilePaths",
]
