"""Tests for `anki-gitify diff`.

Mutation matrix: applies each named mutation to a hand-built base gitified
tree, runs the diff, and asserts on (a) JSON shape via golden files and
(b) anchor strings in the polished text output. One end-to-end test exercises
the `git worktree add` lifecycle by diffing between two committed shas.

To refresh golden files after an intentional shape change, set
``ANKI_GITIFY_UPDATE_GOLDENS=1`` and re-run the suite. Goldens live under
``tests/golden/diff/``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

import pytest
from typer.testing import CliRunner

from anki_gitify.cli import app
from anki_gitify.diff import RevInput, run_diff

from diff_helpers import (
    git,
    init_and_commit,
    mutator_css_edited,
    mutator_deck_added,
    mutator_field_edited,
    mutator_filtered_added,
    mutator_media_added,
    mutator_note_added,
    mutator_note_moved,
    mutator_note_removed,
    mutator_notetype_field_added,
    mutator_tag_added,
    mutator_tag_removed,
    mutator_template_edited,
    write_base_tree,
)


GOLDEN_DIR = Path(__file__).parent / "golden" / "diff"
UPDATE_GOLDENS = bool(os.environ.get("ANKI_GITIFY_UPDATE_GOLDENS"))


# ---------- Normalization for stable goldens ----------


def _normalize(envelope_dict: dict) -> dict:
    """Strip nondeterministic fields so golden comparisons are stable."""
    d = json.loads(json.dumps(envelope_dict))  # deep copy
    d["generated_at"] = "<NORMALIZED>"
    d["tool_version"] = "<NORMALIZED>"
    d["source"]["repo_path"] = "<NORMALIZED>"
    for rev_key in ("rev_a", "rev_b"):
        rev = d.get(rev_key, {})
        if rev.get("kind") == "ref":
            rev["sha"] = "<NORMALIZED>"
            rev["commit_timestamp"] = "<NORMALIZED>"
            rev["commit_subject"] = "<NORMALIZED>"
    return d


def _golden_path(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.json"


def _compare_or_update_golden(name: str, normalized: dict) -> None:
    path = _golden_path(name)
    rendered = json.dumps(normalized, indent=2, ensure_ascii=False) + "\n"
    if UPDATE_GOLDENS or not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8", newline="\n")
        return
    expected = path.read_text(encoding="utf-8")
    if rendered != expected:
        # Surface a focused diff to make failures actionable.
        import difflib

        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=f"golden/{name}.json",
                tofile="actual",
            )
        )
        pytest.fail(f"Golden mismatch for {name}:\n{diff}")


# ---------- Generic helpers ----------


def _setup_with_mutation(tmp_path: Path, mutator: Callable[[Path], None]) -> Path:
    repo = tmp_path / "repo"
    write_base_tree(repo)
    init_and_commit(repo)
    mutator(repo)
    return repo


def _diff_head_vs_wt(repo: Path):
    return run_diff(
        RevInput.from_ref("HEAD"),
        RevInput.working_tree(),
        repo_path=repo,
        output_format="json",
    )


# ---------- Mutation matrix ----------


_MUTATIONS: list[tuple[str, Callable[[Path], None]]] = [
    ("tag_added", mutator_tag_added),
    ("tag_removed", mutator_tag_removed),
    ("field_edited", mutator_field_edited),
    ("note_moved", mutator_note_moved),
    ("note_added", mutator_note_added),
    ("note_removed", mutator_note_removed),
    ("notetype_field_added", mutator_notetype_field_added),
    ("template_edited", mutator_template_edited),
    ("css_edited", mutator_css_edited),
    ("deck_added", mutator_deck_added),
    ("filtered_added", mutator_filtered_added),
    ("media_added", mutator_media_added),
]


@pytest.mark.parametrize("name,mutator", _MUTATIONS, ids=[n for n, _ in _MUTATIONS])
def test_mutation_matches_golden_json(tmp_path: Path, name: str, mutator) -> None:
    repo = _setup_with_mutation(tmp_path, mutator)
    envelope, _ = _diff_head_vs_wt(repo)
    normalized = _normalize(envelope.model_dump(mode="json"))
    _compare_or_update_golden(name, normalized)


def test_no_mutation_is_empty_diff(tmp_path: Path) -> None:
    """Diffing a clean working tree against HEAD yields a fully empty envelope."""
    repo = tmp_path / "repo"
    write_base_tree(repo)
    init_and_commit(repo)
    envelope, rendered = run_diff(
        RevInput.from_ref("HEAD"),
        RevInput.working_tree(),
        repo_path=repo,
        output_format="text",
    )
    assert envelope.is_empty(), envelope.summary
    assert "no semantic changes" in rendered


# ---------- Text-output anchors ----------


def test_text_renders_tag_added_anchor(tmp_path: Path) -> None:
    repo = _setup_with_mutation(tmp_path, mutator_tag_added)
    _, text = run_diff(
        RevInput.from_ref("HEAD"),
        RevInput.working_tree(),
        repo_path=repo,
        output_format="text",
    )
    assert "== note NOTE_A" in text
    assert "~~ changes ~~" in text
    assert "+ covered" in text


def test_text_renders_field_edit_anchor(tmp_path: Path) -> None:
    repo = _setup_with_mutation(tmp_path, mutator_field_edited)
    _, text = run_diff(
        RevInput.from_ref("HEAD"),
        RevInput.working_tree(),
        repo_path=repo,
        output_format="text",
    )
    assert "field Front:" in text
    assert "front a" in text
    assert "front a EDITED" in text


def test_text_renders_deck_added_anchor(tmp_path: Path) -> None:
    repo = _setup_with_mutation(tmp_path, mutator_deck_added)
    _, text = run_diff(
        RevInput.from_ref("HEAD"),
        RevInput.working_tree(),
        repo_path=repo,
        output_format="text",
    )
    assert "== deck tree ==" in text
    assert "+ Top::Sub::Leaf" in text


def test_text_renders_filtered_added_anchor(tmp_path: Path) -> None:
    repo = _setup_with_mutation(tmp_path, mutator_filtered_added)
    _, text = run_diff(
        RevInput.from_ref("HEAD"),
        RevInput.working_tree(),
        repo_path=repo,
        output_format="text",
    )
    assert "++ added filtered_deck Top::Cram" in text
    assert "deck:Top is:due" in text


# ---------- End-to-end: worktree lifecycle ----------


def test_diff_between_two_committed_shas(tmp_path: Path) -> None:
    """Exercise `git worktree add`/`remove` by diffing two refs in one repo."""
    repo = tmp_path / "repo"
    write_base_tree(repo)
    sha_a = init_and_commit(repo, "init")
    mutator_tag_added(repo)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "tag added")
    sha_b = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert sha_a != sha_b

    envelope, _ = run_diff(
        RevInput.from_ref(sha_a),
        RevInput.from_ref(sha_b),
        repo_path=repo,
        output_format="json",
    )
    assert envelope.summary.notes.changed == 1
    assert envelope.notes.changed[0].changes.tags_added == ["covered"]
    assert envelope.notes.changed[0].before.tags == ["alpha"]
    assert envelope.notes.changed[0].after.tags == ["alpha", "covered"]

    # Verify the worktree directory has been cleaned up (no lingering temp
    # dirs holding the gitified data after the diff returned).
    worktree_list = git(repo, "worktree", "list").stdout
    # The only entry should be the main worktree itself.
    assert worktree_list.count("\n") == 1, worktree_list


# ---------- CLI surface ----------


runner = CliRunner()


def test_cli_diff_default_is_head_vs_working_tree(tmp_path: Path, monkeypatch) -> None:
    repo = _setup_with_mutation(tmp_path, mutator_tag_added)
    result = runner.invoke(app, ["diff", "--repo", str(repo), "--color", "never"])
    assert result.exit_code == 0, result.output
    assert "== note NOTE_A" in result.output
    assert "+ covered" in result.output


def test_cli_diff_exit_code_flag(tmp_path: Path) -> None:
    repo = _setup_with_mutation(tmp_path, mutator_tag_added)
    result = runner.invoke(
        app, ["diff", "--repo", str(repo), "--color", "never", "--exit-code"]
    )
    assert result.exit_code == 1, result.output


def test_cli_diff_exit_code_clean_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_base_tree(repo)
    init_and_commit(repo)
    result = runner.invoke(
        app, ["diff", "--repo", str(repo), "--color", "never", "--exit-code"]
    )
    assert result.exit_code == 0, result.output
    assert "no semantic changes" in result.output


def test_cli_diff_json_format(tmp_path: Path) -> None:
    repo = _setup_with_mutation(tmp_path, mutator_tag_added)
    result = runner.invoke(
        app, ["diff", "--repo", str(repo), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["schema_version"] == 1
    assert data["summary"]["notes"]["changed"] == 1
    assert data["notes"]["changed"][0]["changes"]["tags_added"] == ["covered"]


def test_cli_diff_compact_json_is_one_line(tmp_path: Path) -> None:
    repo = _setup_with_mutation(tmp_path, mutator_tag_added)
    result = runner.invoke(
        app,
        ["diff", "--repo", str(repo), "--format", "json", "--compact"],
    )
    assert result.exit_code == 0, result.output
    # compact JSON has no leading whitespace on subkeys
    assert "  " not in result.output[:200]


def test_cli_diff_output_to_file(tmp_path: Path) -> None:
    repo = _setup_with_mutation(tmp_path, mutator_tag_added)
    out = tmp_path / "diff.json"
    result = runner.invoke(
        app,
        [
            "diff",
            "--repo",
            str(repo),
            "--format",
            "json",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert data["summary"]["notes"]["changed"] == 1


def test_cli_diff_no_repo_errors_clearly(tmp_path: Path, monkeypatch) -> None:
    """Running outside a gitified repo (and without --repo) errors cleanly."""
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    result = runner.invoke(app, ["diff"])
    assert result.exit_code == 1
    assert "gitify.yml" in result.output


def test_cli_diff_non_git_repo_errors_clearly(tmp_path: Path) -> None:
    """A --repo pointing outside a git work tree surfaces a clear git error."""
    plain = tmp_path / "plain"
    plain.mkdir()
    result = runner.invoke(app, ["diff", "--repo", str(plain)])
    assert result.exit_code == 1
    assert "not inside a git work tree" in result.output


def test_cli_diff_bad_ref_errors(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_base_tree(repo)
    init_and_commit(repo)
    result = runner.invoke(
        app, ["diff", "nonexistent-ref", "--repo", str(repo), "--color", "never"]
    )
    assert result.exit_code == 1
    assert "nonexistent-ref" in result.output


# ---------- Warnings ----------


def test_working_tree_dirty_warning(tmp_path: Path) -> None:
    """Re-exporting in the working tree (newer exported_at) emits the dirty warning."""
    repo = tmp_path / "repo"
    write_base_tree(repo)
    init_and_commit(repo)
    # Bump the working tree's gitify.yml timestamp.
    gitify = repo / "gitify.yml"
    gitify.write_text(
        gitify.read_text().replace("2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"),
        encoding="utf-8",
        newline="\n",
    )
    envelope, _ = run_diff(
        RevInput.from_ref("HEAD"),
        RevInput.working_tree(),
        repo_path=repo,
        output_format="json",
    )
    kinds = [w.kind for w in envelope.warnings]
    assert "working_tree_dirty_gitify_yml" in kinds


def test_missing_gitify_yml_warning(tmp_path: Path) -> None:
    """If working tree's gitify.yml is missing, a warning fires and diff still runs."""
    repo = tmp_path / "repo"
    write_base_tree(repo)
    init_and_commit(repo)
    (repo / "gitify.yml").unlink()
    envelope, _ = run_diff(
        RevInput.from_ref("HEAD"),
        RevInput.working_tree(),
        repo_path=repo,
        # We need a valid gitify.yml at the time `find_gitified_repo` is
        # called; pass --repo explicitly to skip the walk-up.
        output_format="json",
    )
    kinds = [w.kind for w in envelope.warnings]
    assert "missing_gitify_yml" in kinds


def test_schema_mismatch_warning(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_base_tree(repo)
    init_and_commit(repo)
    gitify = repo / "gitify.yml"
    gitify.write_text(
        gitify.read_text().replace("schema_version: 1", "schema_version: 99"),
        encoding="utf-8",
        newline="\n",
    )
    envelope, _ = run_diff(
        RevInput.from_ref("HEAD"),
        RevInput.working_tree(),
        repo_path=repo,
        output_format="json",
    )
    kinds = [w.kind for w in envelope.warnings]
    assert "schema_mismatch" in kinds


# ---------- find-gitified-repo walk-up ----------


def test_find_gitified_repo_walks_up_from_subdir(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    write_base_tree(repo)
    init_and_commit(repo)
    # Run with CWD inside a subdir of the gitified tree; --repo not passed.
    nested = repo / "decks" / "Sub"
    assert nested.is_dir()
    monkeypatch.chdir(nested)
    result = runner.invoke(app, ["diff", "--color", "never"])
    assert result.exit_code == 0, result.output
    assert "no semantic changes" in result.output
