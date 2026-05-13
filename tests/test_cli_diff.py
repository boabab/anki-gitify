"""End-to-end tests for the `anki-gitify diff` subcommand."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from anki_gitify.cli import app


runner = CliRunner()


_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=_GIT_ENV,
        check=True,
        capture_output=True,
    )


def _export(repo: Path, collection: Path) -> None:
    result = runner.invoke(
        app,
        ["export", "Top", str(repo), "--collection", str(collection), "--force"],
    )
    assert result.exit_code == 0, result.output


def _init_and_commit(repo: Path) -> None:
    _git("init", "-q", cwd=repo)
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)


def _read_csv(path: Path) -> list[list[str]]:
    import csv

    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    import csv

    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\n")
        w.writerows(rows)


def test_diff_empty_for_unchanged_repo(tmp_path: Path, fixture_basic) -> None:
    repo = tmp_path / "gitified"
    _export(repo, fixture_basic.profile.collection)
    _init_and_commit(repo)

    result = runner.invoke(app, ["diff", "--repo", str(repo)], env=_GIT_ENV)
    assert result.exit_code == 0, result.output
    assert "No semantic changes" in result.output


def test_diff_detects_tag_addition(tmp_path: Path, fixture_basic) -> None:
    repo = tmp_path / "gitified"
    _export(repo, fixture_basic.profile.collection)
    _init_and_commit(repo)

    notes_csv = repo / "notes" / "bidirectional.csv"
    rows = _read_csv(notes_csv)
    # rows[0] = header, rows[1] = first note
    rows[1][2] = rows[1][2] + " brandnew"  # append a tag in the space-joined column
    _write_csv(notes_csv, rows)

    result = runner.invoke(app, ["diff", "--repo", str(repo)], env=_GIT_ENV)
    assert result.exit_code == 0, result.output
    assert "tags added:" in result.output
    assert "brandnew" in result.output


def test_diff_detects_deck_move(tmp_path: Path, fixture_basic) -> None:
    repo = tmp_path / "gitified"
    _export(repo, fixture_basic.profile.collection)
    _init_and_commit(repo)

    notes_csv = repo / "notes" / "bidirectional.csv"
    rows = _read_csv(notes_csv)
    original = rows[1][1]
    new = "Top::Other" if original != "Top::Other" else "Top::Sub"
    rows[1][1] = new
    _write_csv(notes_csv, rows)

    result = runner.invoke(app, ["diff", "--repo", str(repo)], env=_GIT_ENV)
    assert result.exit_code == 0, result.output
    assert f"deck: {original} -> {new}" in result.output


def test_diff_detects_template_html_edit(tmp_path: Path, fixture_basic) -> None:
    repo = tmp_path / "gitified"
    _export(repo, fixture_basic.profile.collection)
    _init_and_commit(repo)

    front_html = repo / "notetypes" / "bidirectional" / "templates" / "00-front-back" / "front.html"
    front_html.write_text("{{Front}} edited", encoding="utf-8")

    result = runner.invoke(app, ["diff", "--repo", str(repo)], env=_GIT_ENV)
    assert result.exit_code == 0, result.output
    assert "Notetypes" in result.output
    assert "template" in result.output
    assert "front.html" in result.output


def test_diff_markdown_format(tmp_path: Path, fixture_basic) -> None:
    repo = tmp_path / "gitified"
    _export(repo, fixture_basic.profile.collection)
    _init_and_commit(repo)

    notes_csv = repo / "notes" / "bidirectional.csv"
    rows = _read_csv(notes_csv)
    rows[1][2] = rows[1][2] + " mdtag"
    _write_csv(notes_csv, rows)

    result = runner.invoke(
        app, ["diff", "--repo", str(repo), "--format", "markdown"], env=_GIT_ENV
    )
    assert result.exit_code == 0, result.output
    assert "## Summary" in result.output
    assert "## Notes" in result.output
    assert "mdtag" in result.output
    # no ANSI escape codes
    assert "\x1b[" not in result.output


def test_diff_json_format(tmp_path: Path, fixture_basic) -> None:
    repo = tmp_path / "gitified"
    _export(repo, fixture_basic.profile.collection)
    _init_and_commit(repo)

    notes_csv = repo / "notes" / "bidirectional.csv"
    rows = _read_csv(notes_csv)
    rows[1][2] = rows[1][2] + " jsontag"
    _write_csv(notes_csv, rows)

    result = runner.invoke(
        app, ["diff", "--repo", str(repo), "--format", "json"], env=_GIT_ENV
    )
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    changed = parsed["notes"]["changed"]
    assert len(changed) == 1
    assert "jsontag" in changed[0]["tags_added"]


def test_diff_against_two_explicit_refs(tmp_path: Path, fixture_basic) -> None:
    repo = tmp_path / "gitified"
    _export(repo, fixture_basic.profile.collection)
    _init_and_commit(repo)

    # second commit with a tag change
    notes_csv = repo / "notes" / "bidirectional.csv"
    rows = _read_csv(notes_csv)
    rows[1][2] = rows[1][2] + " refcompare"
    _write_csv(notes_csv, rows)
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "tag", cwd=repo)

    result = runner.invoke(
        app, ["diff", "HEAD~1", "HEAD", "--repo", str(repo)], env=_GIT_ENV
    )
    assert result.exit_code == 0, result.output
    assert "refcompare" in result.output


def test_diff_errors_on_unknown_ref(tmp_path: Path, fixture_basic) -> None:
    repo = tmp_path / "gitified"
    _export(repo, fixture_basic.profile.collection)
    _init_and_commit(repo)

    result = runner.invoke(
        app, ["diff", "does-not-exist", "--repo", str(repo)], env=_GIT_ENV
    )
    assert result.exit_code == 1
    assert "does-not-exist" in result.output or "failed" in result.output.lower()


def test_diff_errors_outside_git_repo(tmp_path: Path, fixture_basic) -> None:
    repo = tmp_path / "gitified"
    _export(repo, fixture_basic.profile.collection)
    # NOT a git repo

    result = runner.invoke(app, ["diff", "--repo", str(repo)], env=_GIT_ENV)
    assert result.exit_code == 1


def test_diff_works_when_gitified_is_subdir_of_repo(tmp_path: Path, fixture_basic) -> None:
    """The gitified dir can live below the git root; diff should still work."""
    root = tmp_path / "monorepo"
    root.mkdir()
    _git("init", "-q", cwd=root)
    nested = root / "decks" / "japanese"
    nested.mkdir(parents=True)
    _export(nested, fixture_basic.profile.collection)
    _git("add", ".", cwd=root)
    _git("commit", "-q", "-m", "init", cwd=root)

    notes_csv = nested / "notes" / "bidirectional.csv"
    rows = _read_csv(notes_csv)
    rows[1][2] = rows[1][2] + " nested"
    _write_csv(notes_csv, rows)

    result = runner.invoke(app, ["diff", "--repo", str(nested)], env=_GIT_ENV)
    assert result.exit_code == 0, result.output
    assert "nested" in result.output
