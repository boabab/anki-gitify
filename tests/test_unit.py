"""Unit tests for utility modules."""

from __future__ import annotations

from anki_gitify import fingerprint, media_refs
from anki_gitify.naming import Slugger


def test_fingerprint_is_deterministic() -> None:
    a = fingerprint.model_id_for("Bidirectional")
    b = fingerprint.model_id_for("Bidirectional")
    assert a == b
    # Different name → different id
    c = fingerprint.model_id_for("Cloze1")
    assert a != c
    # 63-bit positive
    assert 0 < a < (1 << 63)
    assert 0 < c < (1 << 63)


def test_fingerprint_model_vs_deck_disjoint() -> None:
    """A notetype and a deck with the same display name must not collide."""
    assert fingerprint.model_id_for("Stuff") != fingerprint.deck_id_for("Stuff")


def test_slugger_collisions() -> None:
    s = Slugger()
    assert s.slug("Basic") == "basic"
    # Same exact name returns the same slug (memoized)
    assert s.slug("Basic") == "basic"
    # A different name that slugifies to the same string gets suffixed
    assert s.slug("Basic ") == "basic-2"
    assert s.slug("BASIC") == "basic-3"
    # Unicode falls back to ASCII
    assert s.slug("日本語") in {"unnamed", "ri-ben-yu"}  # depends on NFKD


def test_media_refs() -> None:
    html = (
        "<img src=\"sun.png\"> see also "
        "<img src='moon.jpg' alt=x> "
        "audio: [sound:hello.mp3] and [sound:long file.wav] "
        "<source src=\"clip.webm\">"
    )
    refs = media_refs.extract_refs(html)
    assert refs == {"sun.png", "moon.jpg", "hello.mp3", "long file.wav", "clip.webm"}


def test_media_refs_skips_remote_and_data_uri() -> None:
    html = "<img src=\"https://example.com/x.png\"> <img src=\"data:image/png;base64,abc\">"
    assert media_refs.extract_refs(html) == set()


def test_media_refs_empty() -> None:
    assert media_refs.extract_refs("") == set()
    assert media_refs.extract_refs("plain text, no media") == set()
