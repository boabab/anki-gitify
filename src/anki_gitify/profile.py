"""Locate the Anki base directory, profile, and collection.anki2 path."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


# Files at the top of the Anki base directory that are not profile directories.
_NON_PROFILE = {
    "addons21",
    "logs",
    "crash.log",
    "prefs21.db",
    "prefs.db",
    ".bzEmpty",
    "README.txt",
    "README",
}


@dataclass(frozen=True)
class ProfilePaths:
    base: Path
    profile: str
    collection: Path
    media_dir: Path


def default_anki_base() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Anki2"
    if sys.platform == "win32":
        # Anki uses APPDATA on Windows
        import os
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Anki2"
        return Path.home() / "AppData" / "Roaming" / "Anki2"
    # Linux / others
    return Path.home() / ".local" / "share" / "Anki2"


def list_profiles(base: Path) -> list[str]:
    if not base.is_dir():
        return []
    return sorted(
        entry.name
        for entry in base.iterdir()
        if entry.is_dir() and entry.name not in _NON_PROFILE and not entry.name.startswith(".")
    )


def resolve_profile_paths(
    profile: str | None = None,
    base: Path | None = None,
    collection_override: Path | None = None,
) -> ProfilePaths:
    """Resolve to a concrete (base, profile, collection.anki2, media dir).

    If ``collection_override`` is provided, the profile/base are inferred from the
    parent dirs (best-effort) and the override path is used for the collection.
    """
    if collection_override is not None:
        col = collection_override
        if not col.is_file():
            raise FileNotFoundError(f"Collection not found: {col}")
        # parent is the profile directory
        profile_dir = col.parent
        media = profile_dir / "collection.media"
        return ProfilePaths(
            base=profile_dir.parent,
            profile=profile_dir.name,
            collection=col,
            media_dir=media,
        )

    base = base or default_anki_base()
    if not base.is_dir():
        raise FileNotFoundError(
            f"Anki base directory not found: {base}\n"
            "Pass --collection PATH to point at a collection.anki2 directly."
        )

    profiles = list_profiles(base)
    if not profiles:
        raise FileNotFoundError(f"No Anki profiles found in {base}")

    if profile is None:
        if len(profiles) == 1:
            profile = profiles[0]
        else:
            joined = ", ".join(profiles)
            raise ValueError(
                f"Multiple Anki profiles available ({joined}). "
                "Pass --profile NAME to choose one."
            )
    if profile not in profiles:
        joined = ", ".join(profiles)
        raise ValueError(f"Profile {profile!r} not found. Available: {joined}")

    profile_dir = base / profile
    col = profile_dir / "collection.anki2"
    if not col.is_file():
        raise FileNotFoundError(
            f"collection.anki2 not found in profile {profile!r}: {col}"
        )
    media = profile_dir / "collection.media"
    return ProfilePaths(base=base, profile=profile, collection=col, media_dir=media)
