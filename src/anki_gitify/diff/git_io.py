"""Materialize a git revision of a gitified repo into a temp directory."""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class GitError(RuntimeError):
    pass


def _run_git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {stderr}") from None
    return proc.stdout.decode("utf-8", errors="replace").strip()


def repo_toplevel(path: Path) -> Path:
    """Return the git work-tree root that contains `path`."""
    if not path.exists():
        raise GitError(f"path does not exist: {path}")
    start = path if path.is_dir() else path.parent
    top = _run_git(start, "rev-parse", "--show-toplevel")
    if not top:
        raise GitError(f"{path} is not inside a git work tree")
    return Path(top)


def resolve_ref(repo: Path, ref: str) -> str:
    """Verify a ref exists and resolve it to a commit sha (raises GitError otherwise)."""
    return _run_git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def subpath_in_repo(repo: Path) -> str:
    """Return the gitified dir's path relative to the git toplevel ('' if equal)."""
    top = repo_toplevel(repo)
    try:
        rel = repo.resolve().relative_to(top.resolve())
    except ValueError as exc:
        raise GitError(f"{repo} is not inside {top}") from exc
    s = str(rel)
    return "" if s == "." else s


@contextmanager
def materialize_revision(repo: Path, ref: str) -> Iterator[Path]:
    """Yield a path to the extracted contents of `ref` for the given gitified dir.

    If the gitified dir is the git toplevel, the yielded path is the tempdir.
    If it's a subdir, the yielded path is `<tempdir>/<subpath>`. The tempdir
    is cleaned up on context exit.
    """
    top = repo_toplevel(repo)
    sub = subpath_in_repo(repo)

    args = ["archive", "--format=tar", ref]
    if sub:
        args += ["--", sub]
    try:
        proc = subprocess.run(
            ["git", "-C", str(top), *args],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git archive {ref} failed: {stderr}") from None

    with tempfile.TemporaryDirectory(prefix="anki-gitify-diff-") as td:
        tdpath = Path(td)
        with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
            tar.extractall(tdpath, filter="data")
        yield tdpath / sub if sub else tdpath
