"""End-to-end tests for the textconv and install-diff-driver subcommands."""

from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from anki_gitify.cli import app


runner = CliRunner()


# Hermetic git env: ignore the host's global/system config so signing rules,
# default-branch tweaks, etc. don't bleed into these tests.
_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        check=True,
    )


def _write_notes_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\n")
        w.writerows(rows)


def test_textconv_command_humanizes_notes_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "notes.csv"
    _write_notes_csv(
        csv_path,
        [
            ["guid", "deck_path", "tags", "Front", "Back"],
            ["abc", "Top::Sub", "kanji n5", "日", "sun, day"],
        ],
    )

    result = runner.invoke(app, ["textconv", str(csv_path)])
    assert result.exit_code == 0, result.output
    assert "== note abc ==" in result.output
    assert "deck: Top::Sub" in result.output
    assert "  - kanji" in result.output


def test_textconv_command_passes_unknown_files_through(tmp_path: Path) -> None:
    f = tmp_path / "style.css"
    f.write_text(".card { color: red; }\n", encoding="utf-8")
    result = runner.invoke(app, ["textconv", str(f)])
    assert result.exit_code == 0, result.output
    assert ".card { color: red; }" in result.output


def test_install_diff_driver_writes_gitattributes_and_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)

    result = runner.invoke(app, ["install-diff-driver", str(repo)], env=_GIT_ENV)
    assert result.exit_code == 0, result.output

    gitattr = (repo / ".gitattributes").read_text()
    assert "notes/*.csv diff=anki-gitify" in gitattr
    assert "cards.csv diff=anki-gitify" in gitattr
    assert ">>> anki-gitify diff driver >>>" in gitattr

    cfg = _git("config", "--get", "diff.anki-gitify.textconv", cwd=repo)
    assert "textconv" in cfg.stdout


def test_install_diff_driver_is_idempotent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)

    runner.invoke(app, ["install-diff-driver", str(repo)], env=_GIT_ENV)
    first = (repo / ".gitattributes").read_text()
    runner.invoke(app, ["install-diff-driver", str(repo)], env=_GIT_ENV)
    second = (repo / ".gitattributes").read_text()
    assert first == second
    # only one block, not two
    assert second.count(">>> anki-gitify diff driver >>>") == 1


def test_install_diff_driver_preserves_existing_gitattributes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    (repo / ".gitattributes").write_text("*.png binary\n", encoding="utf-8")

    result = runner.invoke(app, ["install-diff-driver", str(repo)], env=_GIT_ENV)
    assert result.exit_code == 0, result.output
    text = (repo / ".gitattributes").read_text()
    assert "*.png binary" in text
    assert "notes/*.csv diff=anki-gitify" in text


def test_install_diff_driver_uninstall_removes_block(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    (repo / ".gitattributes").write_text("*.png binary\n", encoding="utf-8")

    runner.invoke(app, ["install-diff-driver", str(repo)], env=_GIT_ENV)
    result = runner.invoke(
        app, ["install-diff-driver", str(repo), "--uninstall"], env=_GIT_ENV
    )
    assert result.exit_code == 0, result.output
    text = (repo / ".gitattributes").read_text()
    assert "*.png binary" in text
    assert "anki-gitify" not in text

    cfg = subprocess.run(
        ["git", "-C", str(repo), "config", "--get", "diff.anki-gitify.textconv"],
        env=_GIT_ENV,
        capture_output=True,
        text=True,
    )
    assert cfg.returncode != 0  # unset


def test_install_diff_driver_errors_outside_git_repo(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    result = runner.invoke(app, ["install-diff-driver", str(not_a_repo)], env=_GIT_ENV)
    assert result.exit_code == 1
    assert "not inside a git work tree" in result.output


def test_textconv_end_to_end_via_git_diff(tmp_path: Path) -> None:
    """Wire the driver into a real git repo and verify `git diff` shows humanized output."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)

    runner.invoke(app, ["install-diff-driver", str(repo)], env=_GIT_ENV)

    notes = repo / "notes" / "bidirectional.csv"
    _write_notes_csv(
        notes,
        [
            ["guid", "deck_path", "tags", "Front", "Back"],
            ["g1", "Top::Sub", "kanji", "before", "B"],
        ],
    )
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)

    _write_notes_csv(
        notes,
        [
            ["guid", "deck_path", "tags", "Front", "Back"],
            ["g1", "Top::Sub", "kanji n5", "before", "B"],
        ],
    )

    diff = _git("diff", cwd=repo)
    # the humanized diff inserts one line ("  - n5") rather than rewriting the
    # whole CSV row. There must be no "-...kanji..." style raw-CSV deletion.
    assert "+  - n5" in diff.stdout, diff.stdout
    assert "kanji n5" not in diff.stdout, diff.stdout
