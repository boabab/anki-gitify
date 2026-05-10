"""Deterministic YAML I/O for the gitified format."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def dump_yaml(data: Any, path: Path) -> None:
    """Write `data` as YAML to `path` deterministically (sorted keys, LF newlines)."""
    text = yaml.safe_dump(
        data,
        default_flow_style=False,
        sort_keys=True,
        allow_unicode=True,
        width=4096,
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
