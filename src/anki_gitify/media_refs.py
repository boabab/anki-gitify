"""Find media filename references in field/template HTML."""

from __future__ import annotations

import re


_IMG_SRC = re.compile(r"""<img\s+[^>]*src\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_SOURCE_SRC = re.compile(r"""<source\s+[^>]*src\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_AUDIO_TAG = re.compile(r"""\[sound:([^\]]+)\]""")


def extract_refs(html: str) -> set[str]:
    """Return media filenames referenced from HTML/Anki-flavor fields.

    Skips data URIs (`data:image/...`) and remote URLs (`http://`, `https://`).
    Anki's media folder is a flat namespace of local filenames only.
    """
    if not html:
        return set()
    refs: set[str] = set()
    for pattern in (_IMG_SRC, _SOURCE_SRC, _AUDIO_TAG):
        for match in pattern.findall(html):
            if match.startswith(("http://", "https://", "data:", "//")):
                continue
            refs.add(match)
    return refs
