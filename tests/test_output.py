"""Tests for OutputWriter (metadata_enricher.output)."""

import json
from pathlib import Path

import pytest

from metadata_enricher.output import OutputWriter
from metadata_enricher.types import MetadataDocument


class FakeSchema:
    """Minimal schema stub for testing OutputWriter."""

    @property
    def name(self) -> str:
        return "fake"

    @property
    def version(self) -> str:
        return "1.0"

    def get_field_order(self) -> list[str]:
        return ["titles", "creators", "descriptions", "publisher"]

    def get_required_fields(self) -> list[str]:
        return ["titles"]


@pytest.fixture
def schema() -> FakeSchema:
    return FakeSchema()


@pytest.fixture
def writer(schema: FakeSchema) -> OutputWriter:
    return OutputWriter(schema)


class TestFormatJson:
    """OutputWriter.format_json — schema-driven JSON formatting."""

    def test_format_json_ordered_fields(self, writer: OutputWriter):
        """Fields appear in schema order (titles before creators)."""
        doc = MetadataDocument(
            fields={
                "creators": [{"creator_name": "Alice"}],
                "titles": [{"title": "My Paper"}],
            }
        )
        result = writer.format_json(doc)
        data = json.loads(result)
        keys = list(data.keys())
        assert keys == ["titles", "creators"], f"Expected order titles, creators; got {keys}"

    def test_format_json_includes_extra_fields(self, writer: OutputWriter):
        """Fields not in field_order appear at end, alphabetically."""
        doc = MetadataDocument(
            fields={
                "titles": [{"title": "Test"}],
                "languages": [{"code": "en"}],
                "creators": [{"creator_name": "Bob"}],
                "rights": [{"right": "open"}],
            }
        )
        result = writer.format_json(doc)
        data = json.loads(result)
        keys = list(data.keys())
        assert keys[:2] == ["titles", "creators"]
        assert keys[2:] == ["languages", "rights"]

    def test_format_json_empty_document(self, writer: OutputWriter):
        """Empty MetadataDocument produces '{}'."""
        doc = MetadataDocument()
        result = writer.format_json(doc)
        assert result == "{}"

    def test_format_json_skips_missing_ordered_fields(self, writer: OutputWriter):
        """Ordered fields absent from document are skipped."""
        doc = MetadataDocument(fields={"publisher": "Oxford University Press"})
        result = writer.format_json(doc)
        data = json.loads(result)
        assert data == {"publisher": "Oxford University Press"}


class TestWrite:
    """OutputWriter.write — writing to stdout, file, or directory."""

    def test_write_to_stdout(self, writer: OutputWriter, capsys: pytest.CaptureFixture[str]):
        """output_path=None prints to stdout and returns the JSON string."""
        doc = MetadataDocument(fields={"titles": [{"title": "Printed"}]})
        result = writer.write(doc)
        captured = capsys.readouterr()
        assert captured.out.strip() == result
        data = json.loads(result)
        assert data == {"titles": [{"title": "Printed"}]}

    def test_write_to_file(self, writer: OutputWriter, tmp_path: Path):
        """output_path=Path writes JSON to that file."""
        target = tmp_path / "output.json"
        doc = MetadataDocument(fields={"titles": [{"title": "File Test"}]})
        result = writer.write(doc, output_path=target)
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert content == result
        data = json.loads(content)
        assert data == {"titles": [{"title": "File Test"}]}

    def test_write_to_directory_generates_filename(self, writer: OutputWriter, tmp_path: Path):
        """Directory output_path creates a .json file inside with auto-generated name."""
        doc = MetadataDocument(
            fields={
                "doi": "10.1234/example-doi",
                "titles": [{"title": "Directory Test"}],
            }
        )
        result = writer.write(doc, output_path=tmp_path)
        expected_filename = "10.1234_example-doi.json"
        target = tmp_path / expected_filename
        assert target.exists(), (
            f"Expected file {expected_filename} in {tmp_path}, got {list(tmp_path.iterdir())}"
        )
        content = target.read_text(encoding="utf-8")
        assert content == result
        data = json.loads(content)
        assert data["doi"] == "10.1234/example-doi"
        assert data["titles"] == [{"title": "Directory Test"}]

    def test_write_creates_parent_dirs(self, writer: OutputWriter, tmp_path: Path):
        """Nested path that doesn't exist creates parent directories."""
        nested = tmp_path / "deep" / "nested" / "output.json"
        assert not nested.parent.exists()
        doc = MetadataDocument(fields={"titles": [{"title": "Nested"}]})
        result = writer.write(doc, output_path=nested)
        assert nested.exists()
        data = json.loads(nested.read_text(encoding="utf-8"))
        assert data["titles"] == [{"title": "Nested"}]

    def test_write_to_directory_uses_title_when_no_doi(self, writer: OutputWriter, tmp_path: Path):
        """Without DOI, filename is derived from the title field."""
        doc = MetadataDocument(
            fields={
                "titles": [{"title": "My Research Paper: 2024"}],
            }
        )
        writer.write(doc, output_path=tmp_path)
        expected_part = "MyResearchPaper2024"
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == f"{expected_part}.json"
