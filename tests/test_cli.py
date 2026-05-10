"""End-to-end CLI smoke tests via Typer's CliRunner."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from anki_gitify.cli import app


runner = CliRunner()


def test_cli_export_then_verify_then_import(tmp_path: Path, fixture_basic) -> None:
    out_dir = tmp_path / "out"
    apkg = tmp_path / "deck.apkg"

    # export
    result = runner.invoke(
        app,
        [
            "export",
            "Top",
            str(out_dir),
            "--collection",
            str(fixture_basic.profile.collection),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Exported to" in result.output

    # verify
    result = runner.invoke(app, ["verify", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output

    # import
    result = runner.invoke(app, ["import", str(out_dir), str(apkg)])
    assert result.exit_code == 0, result.output
    assert apkg.is_file()
    assert "Wrote" in result.output


def test_cli_list_decks(tmp_path: Path, fixture_basic) -> None:
    result = runner.invoke(
        app,
        [
            "list-decks",
            "--collection",
            str(fixture_basic.profile.collection),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Top" in result.output
    assert "Top::Sub" in result.output


def test_cli_export_force_required(tmp_path: Path, fixture_basic) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "stale").write_text("x")

    result = runner.invoke(
        app,
        [
            "export",
            "Top",
            str(out_dir),
            "--collection",
            str(fixture_basic.profile.collection),
        ],
    )
    assert result.exit_code == 1
    assert "not empty" in result.output

    # with --force it succeeds
    result = runner.invoke(
        app,
        [
            "export",
            "Top",
            str(out_dir),
            "--collection",
            str(fixture_basic.profile.collection),
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output


def test_cli_verify_detects_md_drift(tmp_path: Path, fixture_with_filtered) -> None:
    out_dir = tmp_path / "out"
    runner.invoke(
        app,
        [
            "export",
            "Top",
            str(out_dir),
            "--collection",
            str(fixture_with_filtered.profile.collection),
        ],
    )
    md_path = out_dir / "FILTERED_DECKS.md"
    md_path.write_text("tampered\n")

    result = runner.invoke(app, ["verify", str(out_dir)])
    assert result.exit_code == 1
    assert "FILTERED_DECKS.md" in result.output
