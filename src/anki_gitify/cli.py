"""Typer-based CLI for anki-gitify."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from .collection_io import open_collection
from .diff import RevInput, run_diff
from .diff.git_revs import GitError
from .export.exporter import export as run_export
from .importer.apply_filtered import apply_filtered as run_apply_filtered
from .importer.importer import CardOverrideError, import_ as run_import
from .importer.verify import verify as run_verify
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


@app.command("apply-filtered")
def apply_filtered_cmd(
    in_dir: Path = typer.Argument(..., help="Path to the gitified directory"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Anki profile name"),
    collection: Optional[Path] = typer.Option(None, "--collection", help="Override path to collection.anki2"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would change without writing"),
) -> None:
    """Apply filtered_decks.yml to a live collection (writes filtered-deck metadata only).

    Anki must be closed. Idempotent: filtered decks that already exist are skipped.
    Names that collide with existing normal decks are reported as conflicts and not applied.
    """
    paths = _resolve_profile(profile, collection)
    try:
        report = run_apply_filtered(in_dir=in_dir, collection_path=paths.collection, dry_run=dry_run)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    prefix = "[dry-run] would " if dry_run else ""
    typer.echo(
        f"{prefix}create={len(report.created)}  "
        f"skipped={len(report.skipped)}  conflicts={len(report.conflicts)}"
    )
    for name in report.created:
        typer.secho(f"  + {name}", fg=typer.colors.GREEN)
    for name in report.skipped:
        typer.echo(f"  = {name} (already a filtered deck)")
    for name in report.conflicts:
        typer.secho(
            f"  ! {name} (a non-filtered deck with this name already exists — skipped)",
            fg=typer.colors.YELLOW,
        )
    if report.conflicts:
        raise typer.Exit(code=2)


@app.command("verify")
def verify_cmd(
    in_dir: Path = typer.Argument(..., help="Path to the gitified directory"),
) -> None:
    """Validate a gitified directory against the schema (no Anki needed)."""
    try:
        report = run_verify(in_dir)
    except (ValueError, FileNotFoundError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    if not report.ok:
        for e in report.errors:
            typer.secho(f"FAIL: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.secho("OK", fg=typer.colors.GREEN)
    typer.echo(
        f"  notetypes={report.notetypes}  notes={report.notes}  "
        f"media={report.media}  filtered_decks={report.filtered_decks}"
    )


@app.command("diff")
def diff_cmd(
    rev_a: Optional[str] = typer.Argument(
        None,
        help="Git ref to use for rev_a (default: HEAD if rev_b omitted, otherwise working tree)",
    ),
    rev_b: Optional[str] = typer.Argument(
        None,
        help="Git ref to use for rev_b (default: working tree)",
    ),
    format: str = typer.Option(
        "text",
        "--format",
        help="Output format: 'json' (UI contract) or 'text' (terminal)",
        case_sensitive=False,
    ),
    exit_code: bool = typer.Option(
        False,
        "--exit-code",
        help="Exit 1 if any semantic change detected (mirrors git diff --exit-code)",
    ),
    abbrev: bool = typer.Option(
        False,
        "--abbrev",
        help="Abbreviate very long template / CSS / field content in text output",
    ),
    color: str = typer.Option(
        "auto",
        "--color",
        help="When to colorize text output: 'always', 'auto', 'never'",
        case_sensitive=False,
    ),
    repo: Optional[Path] = typer.Option(
        None,
        "--repo",
        help="Override the gitified-repo location (default: walk up from CWD)",
    ),
    compact: bool = typer.Option(
        False,
        "--compact",
        help="Emit compact JSON instead of pretty-printed (no effect on text format)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        help="Write to file instead of stdout",
    ),
) -> None:
    """Compute a semantic diff between two states of a gitified deck.

    Positional arguments select revs (refs or omitted for working tree):
      anki-gitify diff                 # HEAD vs working tree
      anki-gitify diff <ref>           # <ref> vs working tree
      anki-gitify diff <ref> <ref>     # any two refs
    """
    fmt = format.lower()
    if fmt not in {"json", "text"}:
        typer.secho(f"--format must be 'json' or 'text' (got {format!r})", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    color_when = color.lower()
    if color_when not in {"always", "auto", "never"}:
        typer.secho(
            f"--color must be 'always', 'auto', or 'never' (got {color!r})",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    # Resolve positional args to two RevInput values.
    if rev_a is None and rev_b is None:
        a_input = RevInput.from_ref("HEAD")
        b_input = RevInput.working_tree()
    elif rev_b is None:
        a_input = RevInput.from_ref(rev_a)
        b_input = RevInput.working_tree()
    else:
        a_input = RevInput.from_ref(rev_a)
        b_input = RevInput.from_ref(rev_b)

    use_color = _resolve_color(color_when, output)

    try:
        envelope, rendered = run_diff(
            a_input,
            b_input,
            repo_path=repo,
            output_format=fmt,  # type: ignore[arg-type]
            color=use_color,
            abbrev=abbrev,
            compact=compact,
        )
    except FileNotFoundError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    except GitError as exc:
        typer.secho(f"git error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    if output is not None:
        output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(rendered)

    if exit_code and not envelope.is_empty():
        raise typer.Exit(code=1)


def _resolve_color(when: str, output: Optional[Path]) -> bool:
    if when == "always":
        return True
    if when == "never":
        return False
    # auto: color only if writing to a TTY
    if output is not None:
        return False
    return sys.stdout.isatty()


if __name__ == "__main__":  # pragma: no cover
    app(prog_name="anki-gitify")
