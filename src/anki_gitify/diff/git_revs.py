"""Git rev materialization for the diff pipeline.

Reading non-working-tree revs is done via `git worktree add --detach` into a
tempdir; the existing loader is then pointed at the worktree path. The working
tree itself is read directly with zero git mediation.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

from .model import RevRef, RevSpec, RevWorkingTree


@dataclass(frozen=True)
class RevInput:
    """User-supplied rev: either a git ref or the working tree."""

    kind: Literal["ref", "working_tree"]
    ref: str | None = None

    @classmethod
    def working_tree(cls) -> "RevInput":
        return cls(kind="working_tree")

    @classmethod
    def from_ref(cls, ref: str) -> "RevInput":
        return cls(kind="ref", ref=ref)


class GitError(RuntimeError):
    pass


def find_gitified_repo(start: Path) -> Path:
    """Walk up from `start` looking for the nearest directory containing `gitify.yml`."""
    current = start.resolve()
    while True:
        if (current / "gitify.yml").is_file():
            return current
        if current.parent == current:
            raise FileNotFoundError(
                f"No gitify.yml found at or above {start}. "
                "Run `anki-gitify diff` from inside a gitified deck or pass --repo."
            )
        current = current.parent


def git_toplevel(path: Path) -> Path:
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise GitError(
            f"{path} is not inside a git work tree (stderr: {exc.stderr.strip()})"
        ) from exc
    return Path(proc.stdout.strip())


def resolve_ref(git_root: Path, ref: str) -> RevRef:
    """Resolve a user-supplied ref to a stable RevRef with sha + commit metadata."""
    try:
        sha = subprocess.run(
            ["git", "-C", str(git_root), "rev-parse", "--verify", f"{ref}^{{commit}}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise GitError(f"Could not resolve git ref {ref!r}: {exc.stderr.strip()}") from exc

    show = subprocess.run(
        ["git", "-C", str(git_root), "show", "-s", "--format=%cI%n%s", sha],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines = show.splitlines()
    commit_timestamp = lines[0] if lines else ""
    commit_subject = lines[1] if len(lines) > 1 else ""
    return RevRef(
        kind="ref",
        ref=ref,
        sha=sha,
        commit_timestamp=commit_timestamp,
        commit_subject=commit_subject,
    )


@contextlib.contextmanager
def materialize_rev(
    gitified_repo: Path,
    rev: RevInput,
) -> Iterator[tuple[Path, RevSpec]]:
    """Yield `(gitified_dir_at_rev, rev_spec)` for the given rev.

    For `working_tree` revs, yields the original path unchanged. For ref revs,
    creates a `git worktree add --detach` in a tempdir, computes the gitified
    dir's relative position under the git root, and yields the corresponding
    path inside the worktree. The worktree is removed on exit.
    """
    if rev.kind == "working_tree":
        yield gitified_repo, RevWorkingTree()
        return

    assert rev.ref is not None
    g_root = git_toplevel(gitified_repo)
    rel = gitified_repo.resolve().relative_to(g_root.resolve())
    rev_spec = resolve_ref(g_root, rev.ref)

    tmp_parent = tempfile.mkdtemp(prefix="anki-gitify-diff-")
    worktree_path = Path(tmp_parent) / "wt"
    try:
        subprocess.run(
            [
                "git",
                "-C",
                str(g_root),
                "worktree",
                "add",
                "--detach",
                "--quiet",
                str(worktree_path),
                rev_spec.sha,
            ],
            check=True,
            capture_output=True,
        )
        yield worktree_path / rel, rev_spec
    finally:
        subprocess.run(
            [
                "git",
                "-C",
                str(g_root),
                "worktree",
                "remove",
                "--force",
                str(worktree_path),
            ],
            check=False,
            capture_output=True,
        )
        # `worktree remove` cleans up the worktree itself; remove our tmp parent
        # afterwards. If anything weird is left behind, rmtree will surface it.
        shutil.rmtree(tmp_parent, ignore_errors=True)
