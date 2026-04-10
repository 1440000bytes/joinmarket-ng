"""CLI tests for jmwalletd."""

from __future__ import annotations

from typer.testing import CliRunner

from jmwalletd.cli import app

runner = CliRunner()


def test_root_help_shows_completion_options() -> None:
    """jmwalletd CLI should expose Typer shell completion options."""
    result = runner.invoke(app, ["--help"], prog_name="jmwalletd")

    assert result.exit_code == 0
    assert "--install-completion" in result.stdout
    assert "--show-completion" in result.stdout
