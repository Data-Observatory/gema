"""Tests for the Typer CLI (metadata_enricher.cli)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from typer.testing import CliRunner

from metadata_enricher.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_temp_config(**overrides: object) -> str:
    """Write a minimal valid YAML config to a temp file and return its path."""
    config_data: dict[str, object] = {
        "schema_name": "datacite-4.6",
        "agents": [
            {
                "id": "a1",
                "name": "Test",
                "fields": ["titles"],
                "prompt": "Test prompt",
                "provider": "p1",
                "model": "test-model",
            }
        ],
        "providers": [{"name": "p1", "base_url": "http://localhost", "api_key_env": "TEST_KEY"}],
        "default_provider": "p1",
    }
    config_data.update(**overrides)
    f = tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False)
    yaml.safe_dump(config_data, f)
    f.close()
    return f.name


def _write_temp_input(content: dict[str, object] | None = None) -> str:
    """Write a minimal valid input JSON to a temp file and return its path."""
    if content is None:
        content = {
            "url": "https://example.org/dataset",
            "title": "Test Dataset",
            "description": "A test dataset for CLI validation.",
        }
    f = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
    import json

    json.dump(content, f)
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVersionOption:
    """--version flag."""

    def test_version_output(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "metagen" in result.stdout


class TestHelpOption:
    """--help flag shows all commands."""

    def test_help_shows_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ["process", "validate", "list-schemas", "list-providers"]:
            assert cmd in result.stdout


class TestListSchemasCommand:
    """list-schemas subcommand."""

    def test_list_schemas_shows_datacite(self) -> None:
        result = runner.invoke(app, ["list-schemas"])
        assert result.exit_code == 0
        assert "datacite-4.6" in result.stdout


class TestValidateCommand:
    """validate subcommand."""

    def test_validate_missing_file(self) -> None:
        result = runner.invoke(app, ["validate", "/nonexistent/path.json"])
        assert result.exit_code == 1

    def test_validate_invalid_schema(self) -> None:
        input_path = _write_temp_input()
        try:
            result = runner.invoke(app, ["validate", input_path, "-s", "nonexistent-schema"])
            assert result.exit_code == 1
        finally:
            os.unlink(input_path)


class TestListProvidersCommand:
    """list-providers subcommand."""

    def test_list_providers_no_config(self) -> None:
        from unittest.mock import patch

        with patch("metadata_enricher.cli.find_config", return_value=None):
            result = runner.invoke(app, ["list-providers"])
        assert result.exit_code == 1

    def test_list_providers_config_not_found_gives_friendly_message(self) -> None:
        """No config anywhere -> a plain-language error, not a raw traceback."""
        from unittest.mock import patch

        with patch(
            "metadata_enricher.cli.find_config",
            side_effect=FileNotFoundError("no configuration file found. Searched:\n  x"),
        ):
            result = runner.invoke(app, ["list-providers"])
        assert result.exit_code == 1
        assert "Traceback" not in result.stderr
        assert "no configuration file found" in result.stderr
        assert "--config" in result.stderr


class TestListKnownProvidersCommand:
    """list-known-providers subcommand -- reads config/providers.yaml (the
    autofill preset pool visor's Settings picker uses), not runtime config."""

    def test_list_known_providers_shows_pool_entries(self) -> None:
        result = runner.invoke(app, ["list-known-providers"])
        assert result.exit_code == 0
        assert "autofill presets" in result.stdout

    def test_list_known_providers_missing_pool_file(self) -> None:
        """--config points at an agents.yaml with no sibling providers.yaml."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            agents_path = Path(tmpdir) / "agents.yaml"
            agents_path.write_text("schema_name: x\nagents: []\nproviders: []\n", encoding="utf-8")
            result = runner.invoke(app, ["list-known-providers", "--config", str(agents_path)])
        assert result.exit_code == 1
        assert "not found" in result.stderr

    def test_list_known_providers_invalid_yaml_gives_friendly_message(self) -> None:
        """--config's sibling providers.yaml exists but isn't a valid pool."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            agents_path = Path(tmpdir) / "agents.yaml"
            agents_path.write_text("schema_name: x\nagents: []\nproviders: []\n", encoding="utf-8")
            (Path(tmpdir) / "providers.yaml").write_text(
                "not: a: valid: providers: pool", encoding="utf-8"
            )
            result = runner.invoke(app, ["list-known-providers", "--config", str(agents_path)])
        assert result.exit_code == 1
        assert "Traceback" not in result.stderr

    def test_list_known_providers_respects_config_option(self) -> None:
        """--config's sibling providers.yaml is used instead of the repo-root one."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            agents_path = Path(tmpdir) / "agents.yaml"
            agents_path.write_text("schema_name: x\nagents: []\nproviders: []\n", encoding="utf-8")
            (Path(tmpdir) / "providers.yaml").write_text(
                "providers:\n"
                "  - name: custom-provider\n"
                "    base_url: https://example.test\n"
                "    api_key_env: CUSTOM_KEY\n",
                encoding="utf-8",
            )
            result = runner.invoke(app, ["list-known-providers", "--config", str(agents_path)])
        assert result.exit_code == 0
        assert "custom-provider" in result.stdout


class TestProcessCommand:
    """process subcommand."""

    def test_process_missing_input_exits_1(self) -> None:
        """Non-existent input path exits with code 1."""
        result = runner.invoke(app, ["process", "/nonexistent/input.json"])
        assert result.exit_code == 1
        assert "Input not found" in result.stderr

    def test_process_config_not_found_gives_friendly_message(self) -> None:
        """No config anywhere -> a plain-language error, not a raw traceback."""
        from unittest.mock import patch

        input_path = _write_temp_input()
        try:
            with patch(
                "metadata_enricher.cli.find_config",
                side_effect=FileNotFoundError("no configuration file found. Searched:\n  x"),
            ):
                result = runner.invoke(app, ["process", input_path])
            assert result.exit_code == 1
            assert "Traceback" not in result.stderr
            assert "no configuration file found" in result.stderr
            assert "--config" in result.stderr
        finally:
            os.unlink(input_path)

    def test_process_missing_config(self) -> None:
        """Missing config file exits with code 1 when input exists."""
        from unittest.mock import patch

        input_path = _write_temp_input()
        try:
            with patch("metadata_enricher.cli.find_config", return_value=None):
                result = runner.invoke(app, ["process", input_path])
            assert result.exit_code == 1
        finally:
            os.unlink(input_path)

    def test_process_with_valid_config(self) -> None:
        """Pipeline runs successfully and produces output."""
        from unittest.mock import patch, MagicMock
        from metadata_enricher.types import MetadataDocument

        input_path = _write_temp_input()
        config_path = _write_temp_config()
        try:
            mock_doc = MetadataDocument()
            mock_doc.set_field("titles", [{"title": "Test"}])

            success_result = MagicMock()
            success_result.configure_mock(
                success=True,
                warnings=[],
                document=mock_doc,
                error=None,
            )

            with (
                patch("metadata_enricher.cli.Pipeline") as mock_pipeline_cls,
                patch("metadata_enricher.cli.OutputWriter"),
            ):
                mock_pipeline = mock_pipeline_cls.return_value
                mock_pipeline.run.return_value = [success_result]

                result = runner.invoke(
                    app,
                    ["process", input_path, "--config", config_path],
                )

                assert result.exit_code == 0
                mock_pipeline_cls.assert_called_once()
                mock_pipeline.run.assert_called_once()
                assert "Processed 1/1" in result.stderr
        finally:
            os.unlink(input_path)
            os.unlink(config_path)

    def test_process_routes_output_to_writer(self) -> None:
        """Successful results go to OutputWriter; errors go to stderr."""
        from unittest.mock import patch, MagicMock
        from metadata_enricher.types import MetadataDocument, ResourceDescription

        input_path = _write_temp_input()
        config_path = _write_temp_config()
        try:
            mock_doc = MetadataDocument()
            mock_doc.set_field("titles", [{"title": "Good"}])

            success_result = MagicMock()
            success_result.configure_mock(
                success=True,
                warnings=[],
                document=mock_doc,
                resource=ResourceDescription(url="test://good"),
                error=None,
            )

            error_result = MagicMock()
            error_result.configure_mock(
                success=False,
                document=None,
                resource=ResourceDescription(url="test://bad"),
                error="Something went wrong",
            )

            with (
                patch("metadata_enricher.cli.Pipeline") as mock_pipeline_cls,
                patch("metadata_enricher.cli.OutputWriter") as mock_output_cls,
            ):
                mock_pipeline = mock_pipeline_cls.return_value
                mock_pipeline.run.return_value = [success_result, error_result]
                mock_writer = mock_output_cls.return_value

                result = runner.invoke(
                    app,
                    ["process", input_path, "--config", config_path],
                )

                # Partial batch failure (1 success, 1 failure) exits 2, not 0 —
                # callers must be able to distinguish "all good" from "some failed".
                assert result.exit_code == 2
                mock_writer.write.assert_called_once()
                assert "Error processing test://bad: Something went wrong" in result.stderr
                assert "Processed 1/2" in result.stderr
        finally:
            os.unlink(input_path)
            os.unlink(config_path)

    def test_process_all_failed_exits_1(self) -> None:
        """When every resource fails, exit code is 1."""
        from unittest.mock import patch, MagicMock
        from metadata_enricher.types import ResourceDescription

        input_path = _write_temp_input()
        config_path = _write_temp_config()
        try:
            error_result = MagicMock()
            error_result.configure_mock(
                success=False,
                document=None,
                resource=ResourceDescription(url="test://fail"),
                error="All broken",
            )

            with (
                patch("metadata_enricher.cli.Pipeline") as mock_pipeline_cls,
                patch("metadata_enricher.cli.OutputWriter"),
            ):
                mock_pipeline = mock_pipeline_cls.return_value
                mock_pipeline.run.return_value = [error_result]

                result = runner.invoke(
                    app,
                    ["process", input_path, "--config", config_path],
                )

                assert result.exit_code == 1
                assert "Processed 0/1" in result.stderr
        finally:
            os.unlink(input_path)
            os.unlink(config_path)

    def test_process_batch_writes_distinct_files_named_from_input_stem(self, tmp_path) -> None:
        """Multiple resources -> --output is treated as a directory, one file per
        resource, named from its *input* filename (never from title/DOI, which can
        collide or be missing).
        """
        import json as jsonlib
        from unittest.mock import patch, MagicMock
        from metadata_enricher.types import MetadataDocument, ResourceDescription

        input_dir = tmp_path / "inputs"
        input_dir.mkdir()
        (input_dir / "alpha.json").write_text(jsonlib.dumps({"title": "A", "url": "u1"}))
        (input_dir / "beta.json").write_text(jsonlib.dumps({"title": "A", "url": "u2"}))

        config_path = _write_temp_config()
        out_dir = tmp_path / "does_not_exist_yet"
        try:
            doc_a = MetadataDocument()
            doc_a.set_field("titles", [{"title": "A"}])
            doc_b = MetadataDocument()
            doc_b.set_field("titles", [{"title": "A"}])

            result_a = MagicMock()
            result_a.configure_mock(
                success=True,
                warnings=[],
                document=doc_a,
                resource=ResourceDescription(url="u1"),
                error=None,
                source_path=str(input_dir / "alpha.json"),
            )
            result_b = MagicMock()
            result_b.configure_mock(
                success=True,
                warnings=[],
                document=doc_b,
                resource=ResourceDescription(url="u2"),
                error=None,
                source_path=str(input_dir / "beta.json"),
            )

            with patch("metadata_enricher.cli.Pipeline") as mock_pipeline_cls:
                mock_pipeline = mock_pipeline_cls.return_value
                mock_pipeline.run.return_value = [result_a, result_b]

                result = runner.invoke(
                    app,
                    [
                        "process",
                        str(input_dir),
                        "--config",
                        config_path,
                        "--output",
                        str(out_dir),
                    ],
                )

            assert result.exit_code == 0, result.stderr
            assert out_dir.is_dir()
            written = {f.name for f in out_dir.iterdir()}
            assert written == {"alpha.json", "beta.json"}
        finally:
            os.unlink(config_path)

    def test_process_batch_rejects_existing_file_as_output(self, tmp_path) -> None:
        """Multiple resources + --output pointing at an existing plain file ->
        a clear error instead of silently overwriting it once per resource."""
        import json as jsonlib
        from unittest.mock import patch, MagicMock
        from metadata_enricher.types import MetadataDocument, ResourceDescription

        input_dir = tmp_path / "inputs"
        input_dir.mkdir()
        (input_dir / "alpha.json").write_text(jsonlib.dumps({"title": "A", "url": "u1"}))
        (input_dir / "beta.json").write_text(jsonlib.dumps({"title": "B", "url": "u2"}))

        config_path = _write_temp_config()
        existing_file = tmp_path / "single_output.json"
        existing_file.write_text("{}")
        try:
            doc = MetadataDocument()
            doc.set_field("titles", [{"title": "A"}])
            result_a = MagicMock()
            result_a.configure_mock(
                success=True, warnings=[], document=doc, resource=ResourceDescription(url="u1"),
                error=None, source_path=str(input_dir / "alpha.json"),
            )
            result_b = MagicMock()
            result_b.configure_mock(
                success=True, warnings=[], document=doc, resource=ResourceDescription(url="u2"),
                error=None, source_path=str(input_dir / "beta.json"),
            )

            with patch("metadata_enricher.cli.Pipeline") as mock_pipeline_cls:
                mock_pipeline = mock_pipeline_cls.return_value
                mock_pipeline.run.return_value = [result_a, result_b]

                result = runner.invoke(
                    app,
                    [
                        "process",
                        str(input_dir),
                        "--config",
                        config_path,
                        "--output",
                        str(existing_file),
                    ],
                )

            assert result.exit_code == 1
            assert "directory" in result.stderr.lower()
        finally:
            os.unlink(config_path)


class TestDotenvLoading:
    """.env must actually be picked up — see docs/CLAUDE.md issue #1."""

    def test_env_file_in_cwd_is_loaded(self, tmp_path, monkeypatch) -> None:
        """A key defined only in ./.env becomes visible to the process via
        os.environ after invoking any command (callback runs load_dotenv())."""
        (tmp_path / ".env").write_text("METAGEN_TEST_DOTENV_VAR=from-dotenv\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("METAGEN_TEST_DOTENV_VAR", raising=False)

        result = runner.invoke(app, ["list-schemas"])

        assert result.exit_code == 0
        assert os.environ.get("METAGEN_TEST_DOTENV_VAR") == "from-dotenv"
