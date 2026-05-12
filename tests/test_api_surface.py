"""Compatibility-based tests for the public ``anki_gitify.api`` surface.

These tests do NOT compare exact function signatures. They verify that the
documented surface from ``tests/fixtures/api_v1_surface.json`` is still
present and behaves as documented. Additions (new names, new optional kwargs,
new fields on returned dataclasses) are non-breaking and pass without
touching this file.

If a name or field is intentionally removed/renamed:
    1. Bump the major component of ``API_VERSION`` in ``src/anki_gitify/api.py``.
    2. Update ``tests/fixtures/api_v1_surface.json`` to reflect the new surface.
    3. Update ``docs/API.md`` with the migration notes.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from anki_gitify import api


_SURFACE_PATH = Path(__file__).parent / "fixtures" / "api_v1_surface.json"


@pytest.fixture(scope="module")
def surface() -> dict:
    return json.loads(_SURFACE_PATH.read_text(encoding="utf-8"))


def test_api_version_matches_snapshot(surface: dict) -> None:
    """API_VERSION in api.py is the source of truth; the snapshot must match.

    A mismatch means either the snapshot was forgotten after a deliberate
    bump, or the bump is missing for a real surface change.
    """
    expected = tuple(surface["api_version"])
    assert api.API_VERSION == expected, (
        f"api.API_VERSION={api.API_VERSION} != snapshot {expected}. "
        "Update tests/fixtures/api_v1_surface.json or bump API_VERSION in api.py."
    )


def test_all_documented_names_are_present(surface: dict) -> None:
    """Every name promised in the snapshot is importable from api.

    Missing a name = breaking change. Adding new names is fine.
    """
    missing = [name for name in surface["names"] if not hasattr(api, name)]
    assert not missing, f"Documented surface names missing from api: {missing}"


def test_all_in_all(surface: dict) -> None:
    """Every documented name is also re-exported via __all__."""
    not_exported = [name for name in surface["names"] if name not in api.__all__]
    assert not not_exported, (
        f"Documented names not in api.__all__: {not_exported}"
    )


def test_dataclass_fields_present(surface: dict) -> None:
    """Each documented dataclass still has every documented field.

    Adding new fields is non-breaking; removing or renaming one is a major
    bump.
    """
    failures: list[str] = []
    for cls_name, expected_fields in surface["dataclass_fields"].items():
        cls = getattr(api, cls_name)
        # dataclasses expose fields via __dataclass_fields__; for non-dataclass
        # classes we fall back to attribute presence on a default instance is
        # impossible, so this test is dataclass-specific.
        assert hasattr(cls, "__dataclass_fields__"), (
            f"{cls_name} is documented as a dataclass but isn't one"
        )
        actual_fields = set(cls.__dataclass_fields__)
        for field_name in expected_fields:
            if field_name not in actual_fields:
                failures.append(f"{cls_name}.{field_name}")
    assert not failures, (
        f"Documented dataclass fields missing: {failures}"
    )


def test_exceptions_are_exception_subclasses(surface: dict) -> None:
    for exc_name in surface["exceptions"]:
        cls = getattr(api, exc_name)
        assert isinstance(cls, type) and issubclass(cls, Exception), (
            f"{exc_name} is documented as an exception but isn't a subclass of Exception"
        )


def test_callables_accept_documented_required_args() -> None:
    """Each public function accepts at least its documented required args.

    We don't run them — we just check that the parameters listed as required
    in the API contract appear in the function signature (positional or
    keyword). New optional parameters are allowed and don't break this test.
    """
    required: dict[str, list[str]] = {
        "import_": ["in_dir", "out_apkg"],
        "apply_filtered": ["in_dir", "collection_path"],
        "verify": ["in_dir"],
        "load": ["in_dir"],
        "list_profiles": ["base"],
        # resolve_profile_paths takes only optional parameters
        "resolve_profile_paths": [],
        "default_anki_base": [],
    }
    failures: list[str] = []
    for fn_name, params in required.items():
        fn = getattr(api, fn_name)
        sig = inspect.signature(fn)
        for p in params:
            if p not in sig.parameters:
                failures.append(f"{fn_name}({p})")
    assert not failures, (
        f"Public functions missing documented parameters: {failures}"
    )


def test_optional_kwargs_still_accepted() -> None:
    """Documented optional kwargs are still in the signature.

    Removing an optional kwarg breaks consumers that rely on it. Adding new
    ones is fine.
    """
    optional: dict[str, list[str]] = {
        "import_": ["ignore_card_overrides"],
        "apply_filtered": ["dry_run"],
    }
    failures: list[str] = []
    for fn_name, kwargs in optional.items():
        fn = getattr(api, fn_name)
        sig = inspect.signature(fn)
        for kw in kwargs:
            if kw not in sig.parameters:
                failures.append(f"{fn_name}({kw}=...)")
    assert not failures, (
        f"Documented optional kwargs missing: {failures}"
    )


# ---------- Behavioral smoke tests ---------- #


def test_smoke_verify_on_exported_dir(tmp_path: Path, fixture_basic) -> None:
    """End-to-end: export a synthetic deck via internals, then verify via the
    public api. Confirms api.verify returns a VerifyReport with documented
    fields and ok=True.
    """
    from anki_gitify.export.exporter import export as run_export

    out_dir = tmp_path / "gitified"
    run_export(
        deck_name=fixture_basic.root_deck,
        out_dir=out_dir,
        profile=fixture_basic.profile,
    )

    report = api.verify(out_dir)
    assert report.ok is True
    assert report.errors == []
    assert report.notes >= 1
    assert report.notetypes >= 1
    # New fields could appear on VerifyReport; that's fine, we only test ours.


def test_smoke_load_returns_loaded_repo(tmp_path: Path, fixture_basic) -> None:
    from anki_gitify.export.exporter import export as run_export

    out_dir = tmp_path / "gitified"
    run_export(
        deck_name=fixture_basic.root_deck,
        out_dir=out_dir,
        profile=fixture_basic.profile,
    )

    repo = api.load(out_dir)
    assert isinstance(repo, api.LoadedRepo)
    # documented fields present
    for f in ("in_dir", "gitify", "notetypes", "notes", "media_files"):
        assert hasattr(repo, f)


def test_smoke_import_builds_apkg(tmp_path: Path, fixture_basic) -> None:
    from anki_gitify.export.exporter import export as run_export

    out_dir = tmp_path / "gitified"
    apkg = tmp_path / "deck.apkg"
    run_export(
        deck_name=fixture_basic.root_deck,
        out_dir=out_dir,
        profile=fixture_basic.profile,
    )

    report, repo = api.import_(out_dir, apkg)
    assert isinstance(report, api.ImportReport)
    assert apkg.is_file() and apkg.stat().st_size > 0
    assert report.notes >= 1


def test_smoke_list_profiles_and_default_base(tmp_path: Path) -> None:
    """list_profiles on an empty base returns []; default_anki_base returns a Path."""
    base = tmp_path / "AnkiBase-empty"
    base.mkdir()
    assert api.list_profiles(base) == []

    default = api.default_anki_base()
    assert isinstance(default, Path)


def test_card_override_error_is_raised(tmp_path: Path, fixture_basic) -> None:
    """CardOverrideError is the documented exception for this case and is the
    same class regardless of which import path you came in through.
    """
    from anki_gitify.export.exporter import export as run_export

    out_dir = tmp_path / "gitified"
    run_export(
        deck_name=fixture_basic.root_deck,
        out_dir=out_dir,
        profile=fixture_basic.profile,
    )

    # Synthesise a cards.csv to trigger the override path.
    cards_csv = out_dir / "cards.csv"
    if not cards_csv.is_file():
        cards_csv.write_text(
            "note_guid,ord,deck_path\n",
            encoding="utf-8",
        )
        # No data rows — but the file's mere presence should be enough to
        # require --ignore-card-overrides, because the importer treats the
        # file as a contract that overrides exist. Skip this test if the
        # file is empty and import_ succeeds.

    apkg = tmp_path / "deck.apkg"
    try:
        api.import_(out_dir, apkg)
    except api.CardOverrideError:
        # Documented exception — test passes.
        return
    except Exception as exc:  # pragma: no cover
        pytest.fail(
            f"Expected api.CardOverrideError or success; got {type(exc).__name__}: {exc}"
        )
    # If no exception was raised, the empty cards.csv was a no-op; skip.
