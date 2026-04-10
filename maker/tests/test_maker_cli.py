"""CLI tests for maker CLI app."""

from __future__ import annotations

from typer.testing import CliRunner

from maker.cli import app

runner = CliRunner()


def test_root_help_shows_completion_options() -> None:
    """Maker CLI should expose Typer shell completion options."""
    result = runner.invoke(app, ["--help"], prog_name="jm-maker")

    assert result.exit_code == 0
    assert "--install-completion" in result.stdout
    assert "--show-completion" in result.stdout
