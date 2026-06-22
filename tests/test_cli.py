"""Tests for the Typer CLI (metadata_enricher.cli)."""

from __future__ import annotations

from typer.testing import CliRunner

from metadata_enricher.cli import app

runner = CliRunner()


class TestCliVersion:
    """--version flag."""

    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "metagen 0.1.0" in result.stdout


class TestCliHelp:
    """--help flag and no-args behavior."""

    def test_help_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ["process", "validate", "list-schemas", "list-providers"]:
            assert cmd in result.stdout

    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # no_args_is_help=True raises SystemExit(2) (usage error) with help text
        assert result.exit_code == 2
        assert "Usage:" in result.stdout


class TestProcessCommand:
    """process subcommand."""

    def test_process_help(self) -> None:
        result = runner.invoke(app, ["process", "--help"])
        assert result.exit_code == 0
        assert "INPUT_PATH" in result.stdout

    def test_process_not_implemented(self) -> None:
        result = runner.invoke(app, ["process", "examples/sample_input01.json"])
        assert result.exit_code == 1
        assert "Not yet implemented" in result.stdout


class TestValidateCommand:
    """validate subcommand."""

    def test_validate_help(self) -> None:
        result = runner.invoke(app, ["validate", "--help"])
        assert result.exit_code == 0
        assert "FILE" in result.stdout


class TestListSchemasCommand:
    """list-schemas subcommand."""

    def test_list_schemas_not_implemented(self) -> None:
        result = runner.invoke(app, ["list-schemas"])
        assert result.exit_code == 1
        assert "Not yet implemented" in result.stdout


class TestListProvidersCommand:
    """list-providers subcommand."""

    def test_list_providers_not_implemented(self) -> None:
        result = runner.invoke(app, ["list-providers"])
        assert result.exit_code == 1
        assert "Not yet implemented" in result.stdout
