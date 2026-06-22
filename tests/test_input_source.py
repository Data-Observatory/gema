"""Tests for InputSource Protocol and FilesystemInputSource."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from metadata_enricher.input_sources.base import InputSource
from metadata_enricher.input_sources.filesystem import FilesystemInputSource
from metadata_enricher.types import ResourceDescription


# ---------------------------------------------------------------------------
# Protocol tests
# ---------------------------------------------------------------------------


class TestInputSourceProtocol:
    """Verify FilesystemInputSource satisfies the InputSource Protocol."""

    def test_isinstance_check(self) -> None:
        """FilesystemInputSource() should be an instance of InputSource."""
        source = FilesystemInputSource()
        assert isinstance(source, InputSource)


# ---------------------------------------------------------------------------
# FilesystemInputSource.fetch tests
# ---------------------------------------------------------------------------


class TestFilesystemFetch:
    """Tests for FilesystemInputSource.fetch()."""

    SAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

    def test_fetch_sample_input01(self) -> None:
        """Fetch sample_input01.json → returns ResourceDescription with expected fields."""
        path = str(self.SAMPLES_DIR / "sample_input01.json")
        result = FilesystemInputSource().fetch(path)

        assert isinstance(result, ResourceDescription)
        assert (
            result.url
            == "https://datos.gob.cl/dataset/gastos-municipales-presas-corporaciones-municipales-presupuesto-abierto"
        )
        assert result.title == "Gastos municipales (presupuesto abierto)"
        assert "gastos municipales" in (result.description or "")
        assert "<html>" in (result.fetched_content or "")

    def test_fetch_nonexistent_file_raises(self) -> None:
        """Fetching a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="not found"):
            FilesystemInputSource().fetch("/nonexistent/path/file.json")

    def test_fetch_malformed_json_raises(self) -> None:
        """Fetching a malformed JSON file raises ValueError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("this is not json")
            tmp_path = f.name

        try:
            with pytest.raises(ValueError, match="Invalid JSON"):
                FilesystemInputSource().fetch(tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_fetch_empty_dict(self) -> None:
        """Fetching an empty JSON object {} → ResourceDescription with all-None fields."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            tmp_path = f.name

        try:
            result = FilesystemInputSource().fetch(tmp_path)
            assert result.url is None
            assert result.title is None
            assert result.description is None
            assert result.doi is None
            assert result.fetched_content is None
        finally:
            os.unlink(tmp_path)

    def test_fetch_extra_fields_preserved(self) -> None:
        """Extra fields (publisher, frequency) are preserved in model_extra."""
        path = str(self.SAMPLES_DIR / "sample_input01.json")
        result = FilesystemInputSource().fetch(path)

        assert result.model_extra is not None
        # sample_input01.json has "publisher" and "frequency"
        extra = result.model_extra
        assert "publisher" in extra
        assert extra["publisher"] == "Ministerio de Hacienda - Gobierno de Chile"
        assert "frequency" in extra
        assert extra["frequency"] == "Mensual"

    def test_fetch_with_doi_field(self) -> None:
        """A file with a doi field populates ResourceDescription.doi."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"doi": "10.1234/test-doi", "url": "https://example.com"}, f)
            tmp_path = f.name

        try:
            result = FilesystemInputSource().fetch(tmp_path)
            assert result.doi == "10.1234/test-doi"
            assert result.url == "https://example.com"
        finally:
            os.unlink(tmp_path)

    def test_fetch_non_dict_json_raises(self) -> None:
        """Fetching a JSON array (not dict) raises ValueError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('["not", "a", "dict"]')
            tmp_path = f.name

        try:
            with pytest.raises(ValueError, match="Expected a JSON object"):
                FilesystemInputSource().fetch(tmp_path)
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# FilesystemInputSource.list_sources tests
# ---------------------------------------------------------------------------


class TestFilesystemListSources:
    """Tests for FilesystemInputSource.list_sources()."""

    SAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

    def test_list_directory(self) -> None:
        """Listing 'examples/' returns .json files in that dir."""
        results = FilesystemInputSource().list_sources(str(self.SAMPLES_DIR))
        assert len(results) >= 1
        # Every result should be a .json file in the examples dir
        for r in results:
            assert r.startswith(str(self.SAMPLES_DIR))
            assert r.endswith(".json")
        # sample_input01.json should be in there
        assert str(self.SAMPLES_DIR / "sample_input01.json") in results

    def test_list_glob(self) -> None:
        """Listing 'examples/*.json' returns same as directory listing."""
        glob_pattern = str(self.SAMPLES_DIR / "*.json")
        results = FilesystemInputSource().list_sources(glob_pattern)
        assert len(results) >= 1
        for r in results:
            assert r.endswith(".json")

    def test_list_single_file(self) -> None:
        """Listing a single existing file returns [filename]."""
        path = str(self.SAMPLES_DIR / "sample_input01.json")
        results = FilesystemInputSource().list_sources(path)
        assert results == [path]

    def test_list_nonexistent_directory(self) -> None:
        """Listing a nonexistent path returns []."""
        results = FilesystemInputSource().list_sources("/tmp/doesnt_exist_xyz/")
        assert results == []

    def test_list_nonexistent_glob(self) -> None:
        """Listing a nonexistent glob pattern returns []."""
        results = FilesystemInputSource().list_sources("/tmp/nothing_*.json")
        assert results == []
