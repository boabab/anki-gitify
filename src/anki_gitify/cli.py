"""Typer-based CLI for anki-gitify."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from .collection_io import open_collection
from .export.exporter import export as run_export
from .export.filtered import render_filtered_md
from .importer.importer import CardOverrideError, import_ as run_import
from .importer.loader import load
from .profile import resolve_profile_paths


app = typer.Typer(
    add_completion=False,
    help="Convert an Anki deck to a git-versionable directory and back to .apkg.",
)


def _resolve_profile(
    profile: Optional[str],
    collection: Optional[Path],
):
    try:
        return resolve_profile_paths(
            profile=profile,
            collection_override=collection,
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None


@app.command("list-decks")
def list_decks_cmd(
    profile: Optional[str] = typer.Option(None, "--profile", help="Anki profile name"),
    collection: Optional[Path] = typer.Option(None, "--collection", help="Override path to collection.anki2"),
) -> None:
    """List the deck names in the resolved Anki collection."""
    paths = _resolve_profile(profile, collection)
    with open_collection(paths.collection) as col:
        names = sorted(e.name for e in col.decks.all_names_and_ids())
    for name in names:
        typer.echo(name)


@app.command("export")
def export_cmd(
    deck_name: str = typer.Argument(..., help="Full deck name to export (use :: for hierarchy)"),
    out_dir: Path = typer.Argument(..., help="Output directory for the gitified deck"),
    profile: Optional[str] = typer.Option(None, "--profile"),
    collection: Optional[Path] = typer.Option(None, "--collection"),
    no_media: bool = typer.Option(False, "--no-media", help="Skip copying referenced media files"),
    force: bool = typer.Option(False, "--force", help="Overwrite a non-empty out_dir"),
) -> None:
    """Export an Anki deck (with subdecks) to a gitified directory."""
    paths = _resolve_profile(profile, collection)
    try:
        report = run_export(
            deck_name=deck_name,
            out_dir=out_dir,
            profile=paths,
            include_media=not no_media,
            force=force,
        )
    except (FileExistsError, ValueError, RuntimeError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Exported to {report.out_dir}")
    typer.echo(
        f"  notetypes={report.notetypes}  notes={report.notes}  cards={report.cards}  "
        f"media={report.media}  filtered_decks={report.filtered_decks}"
    )
    if report.has_card_overrides:
        typer.secho(
            "  cards.csv emitted (some notes have cards distributed across multiple decks).",
            fg=typer.colors.YELLOW,
        )
    if report.media_missing:
        typer.secho(
            f"  WARNING: {len(report.media_missing)} referenced media file(s) missing in collection.media",
            fg=typer.colors.YELLOW,
        )
        for name in report.media_missing[:10]:
            typer.echo(f"    - {name}")
        if len(report.media_missing) > 10:
            typer.echo(f"    ... and {len(report.media_missing) - 10} more")


@app.command("import")
def import_cmd(
    in_dir: Path = typer.Argument(..., help="Path to the gitified directory"),
    out_apkg: Path = typer.Argument(..., help="Path to write the resulting .apkg"),
    ignore_card_overrides: bool = typer.Option(
        False,
        "--ignore-card-overrides",
        help="Required to proceed if cards.csv is present (lossy fallback)",
    ),
) -> None:
    """Convert a gitified directory back into a .apkg ready for Anki File → Import."""
    try:
        report, repo = run_import(
            in_dir=in_dir,
            out_apkg=out_apkg,
            ignore_card_overrides=ignore_card_overrides,
        )
    except CardOverrideError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None
    except (ValueError, FileNotFoundError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Wrote {report.out_apkg}")
    typer.echo(f"  notes={report.notes}  media={report.media_files}")
    typer.echo("Open Anki and use File → Import to add this to your collection.")

    if report.filtered_decks:
        typer.echo("")
        typer.secho(
            f"Exported {report.filtered_decks} filtered deck definition(s) "
            "(not in the .apkg — see gitified dir).",
            fg=typer.colors.CYAN,
        )
        typer.echo(f"  Spec:   {repo.in_dir / 'filtered_decks.yml'}")
        typer.echo(f"  Readme: {repo.in_dir / 'FILTERED_DECKS.md'}")
        typer.echo("To apply: open Anki → Tools → Create Filtered Deck for each entry below.")
        for fd in repo.filtered.filtered_decks:
            search = fd.terms[0].search if fd.terms else ""
            typer.echo(f"  - {fd.name:<40s}  {search}")


@app.command("verify")
def verify_cmd(
    in_dir: Path = typer.Argument(..., help="Path to the gitified directory"),
) -> None:
    """Validate a gitified directory against the schema (no Anki needed)."""
    try:
        repo = load(in_dir)
    except (ValueError, FileNotFoundError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    errors: list[str] = []

    # FILTERED_DECKS.md must agree with filtered_decks.yml regeneration
    md_path = repo.in_dir / "FILTERED_DECKS.md"
    fd_dicts = [fd.model_dump() for fd in repo.filtered.filtered_decks]
    if fd_dicts:
        expected = render_filtered_md(fd_dicts)
        if not md_path.is_file():
            errors.append(f"{md_path} is missing but filtered_decks.yml has entries")
        else:
            actual = md_path.read_text(encoding="utf-8")
            if actual != expected:
                errors.append(f"{md_path} does not match what would be regenerated from filtered_decks.yml")
    else:
        if md_path.is_file():
            errors.append(f"{md_path} exists but filtered_decks.yml is empty")

    # CSV header consistency: already enforced by loader, but the file load itself
    # would have raised. Reaching here means notes parsed cleanly.

    # Media references should exist for at least the most-referenced files.
    # (loader returned `media_files` = all on-disk files; we don't fail on
    #  unreferenced ones.)

    if errors:
        for e in errors:
            typer.secho(f"FAIL: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.secho("OK", fg=typer.colors.GREEN)
    typer.echo(f"  notetypes={len(repo.notetypes)}  notes={len(repo.notes)}  "
               f"media={len(repo.media_files)}  filtered_decks={len(repo.filtered.filtered_decks)}")


if __name__ == "__main__":  # pragma: no cover
    app(prog_name="anki-gitify")
