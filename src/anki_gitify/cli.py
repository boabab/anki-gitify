"""Typer-based CLI for anki-gitify."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer

from . import textconv as textconv_mod
from .collection_io import open_collection
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


@app.command("textconv")
def textconv_cmd(
    path: Path = typer.Argument(..., help="File path (git passes a temp file here)"),
) -> None:
    """Print a humanized rendering of a gitified file to stdout (git diff driver).

    Wired up by `anki-gitify install-diff-driver` so `git diff` shows
    notes/*.csv as one block per note instead of one giant row per line.
    Files we don't know how to humanize are passed through verbatim.
    """
    try:
        rendered = textconv_mod.humanize_path(path)
    except FileNotFoundError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    sys.stdout.write(rendered)


_GITATTR_MARKER_BEGIN = "# >>> anki-gitify diff driver >>>"
_GITATTR_MARKER_END = "# <<< anki-gitify diff driver <<<"
_GITATTR_BODY = "\n".join(
    [
        _GITATTR_MARKER_BEGIN,
        "notes/*.csv diff=anki-gitify",
        "cards.csv diff=anki-gitify",
        _GITATTR_MARKER_END,
    ]
)


def _resolve_anki_gitify_exe() -> str:
    found = shutil.which("anki-gitify")
    if found:
        return found
    # Fall back to the sibling of the active Python interpreter; covers the
    # case where the venv isn't on PATH but its `bin/` has the entry point.
    candidate = Path(sys.executable).parent / "anki-gitify"
    if candidate.is_file():
        return str(candidate)
    typer.secho(
        "Could not find `anki-gitify` on PATH or next to the active Python "
        f"({sys.executable}). Install the package in this Python before "
        "running install-diff-driver.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(code=1)


def _git_toplevel(path: Path) -> Path:
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:
        typer.secho("git executable not found on PATH", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    except subprocess.CalledProcessError:
        typer.secho(
            f"{path} is not inside a git work tree (run `git init` first).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from None
    return Path(proc.stdout.decode("utf-8").strip())


@app.command("install-diff-driver")
def install_diff_driver_cmd(
    repo: Path = typer.Argument(
        Path("."),
        help="Path to the gitified directory (defaults to current dir)",
    ),
    uninstall: bool = typer.Option(False, "--uninstall", help="Remove the driver instead"),
) -> None:
    """Wire up `git diff` to render gitified files in a humanized form.

    Writes/updates `<repo>/.gitattributes` and runs `git config` in the
    enclosing repo so `notes/*.csv` and `cards.csv` are routed through
    `anki-gitify textconv` for diffing. Idempotent.
    """
    repo = repo.resolve()
    if not repo.is_dir():
        typer.secho(f"{repo} is not a directory", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    toplevel = _git_toplevel(repo)
    gitattr = repo / ".gitattributes"

    existing = gitattr.read_text(encoding="utf-8") if gitattr.is_file() else ""
    has_block = _GITATTR_MARKER_BEGIN in existing

    if uninstall:
        if has_block:
            new_text = _strip_block(existing)
            gitattr.write_text(new_text, encoding="utf-8")
            typer.secho(f"Removed driver block from {gitattr}", fg=typer.colors.YELLOW)
        else:
            typer.echo(f"No driver block in {gitattr}; nothing to remove.")
        subprocess.run(
            ["git", "-C", str(toplevel), "config", "--unset", "diff.anki-gitify.textconv"],
            capture_output=True,
            check=False,
        )
        typer.secho("Unset diff.anki-gitify.textconv in repo config.", fg=typer.colors.YELLOW)
        return

    exe = _resolve_anki_gitify_exe()

    if has_block:
        typer.echo(f"{gitattr} already contains the driver block (left as-is).")
    else:
        suffix = "" if existing.endswith("\n") or existing == "" else "\n"
        gitattr.write_text(existing + suffix + _GITATTR_BODY + "\n", encoding="utf-8")
        typer.secho(f"Wrote driver block to {gitattr}", fg=typer.colors.GREEN)

    subprocess.run(
        ["git", "-C", str(toplevel), "config", "diff.anki-gitify.textconv", f"{exe} textconv"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(toplevel), "config", "diff.anki-gitify.cachetextconv", "true"],
        check=True,
    )
    typer.secho(
        f"Configured diff.anki-gitify.textconv = {exe} textconv (in {toplevel}/.git/config)",
        fg=typer.colors.GREEN,
    )
    typer.echo("")
    typer.echo("Try it out:")
    typer.secho("  git diff", fg=typer.colors.CYAN)
    typer.echo(
        "Note: GitHub's PR view doesn't run textconv drivers, so this only "
        "improves your local `git diff` / `git log -p` / IDE diff. For a "
        "structured branch summary, use a custom tool."
    )


def _strip_block(text: str) -> str:
    out_lines: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line.strip() == _GITATTR_MARKER_BEGIN:
            skipping = True
            continue
        if line.strip() == _GITATTR_MARKER_END:
            skipping = False
            continue
        if not skipping:
            out_lines.append(line)
    cleaned = "\n".join(out_lines)
    # collapse the trailing blank line(s) the block left behind
    while cleaned.endswith("\n\n"):
        cleaned = cleaned[:-1]
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"
    return cleaned


if __name__ == "__main__":  # pragma: no cover
    app(prog_name="anki-gitify")
