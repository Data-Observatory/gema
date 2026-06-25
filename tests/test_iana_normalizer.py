"""Tests for enrichers.iana_normalizer — all network calls mocked."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import httpx

from metadata_enricher.enrichers.iana_normalizer import IANANormalizer


# ---------------------------------------------------------------------------
# Helper: minimal IANA XML for refresh tests
# ---------------------------------------------------------------------------

MINIMAL_IANA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<registry xmlns="http://www.iana.org/assignments" id="application">
  <registry id="application">
    <record>
      <name>json</name>
      <file type="template">application/json</file>
      <xref type="rfc" data="rfc8259"/>
    </record>
    <record>
      <name>xml</name>
      <file type="template">application/xml</file>
      <xref type="rfc" data="rfc3023"/>
    </record>
    <record>
      <name>zip</name>
      <file type="template">application/zip</file>
      <xref type="rfc" data="rfc6713"/>
    </record>
  </registry>
</registry>
"""


def _write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_canonical_unchanged(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.normalize("application/json") == "application/json"
        assert n.normalize("text/html") == "text/html"
        assert n.normalize("application/pdf") == "application/pdf"

    def test_whitespace_and_case_normalized(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.normalize("  TEXT/HTML  ") == "text/html"
        assert n.normalize("\tApplication/JSON\n") == "application/json"

    def test_trailing_semicolons_stripped(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.normalize("text/csv;") == "text/csv"
        assert n.normalize("text/csv ;") == "text/csv"

    def test_parameters_stripped(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.normalize("text/html; charset=utf-8") == "text/html"
        assert n.normalize("application/json; charset=utf-8; version=1") == "application/json"

    def test_name_lookup(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.normalize("pdf") == "application/pdf"
        assert n.normalize("csv") == "text/csv"
        assert n.normalize("html") == "text/html"

    def test_unknown_type_preserved(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.normalize("application/x-custom") == "application/x-custom"
        assert n.normalize("image/x-unknown") == "image/x-unknown"

    def test_empty_string_preserved(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.normalize("") == ""
        assert n.normalize("   ") == "   "

    def test_name_lookup_case_insensitive(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.normalize("PDF") == "application/pdf"
        assert n.normalize("CSV") == "text/csv"

    def test_geo_json_with_plus(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.normalize("application/geo+json") == "application/geo+json"


# ---------------------------------------------------------------------------
# is_valid
# ---------------------------------------------------------------------------


class TestIsValid:
    def test_valid_true(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.is_valid("application/json") is True
        assert n.is_valid("text/html") is True
        assert n.is_valid("application/pdf") is True

    def test_invalid_false(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.is_valid("application/x-custom") is False
        assert n.is_valid("x-fake/type") is False

    def test_empty_string_false(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.is_valid("") is False
        assert n.is_valid("   ") is False

    def test_name_lookup_valid(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.is_valid("pdf") is True
        assert n.is_valid("csv") is True

    def test_with_parameters(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "iana.json", mock_iana_data)
        n = IANANormalizer(bundled_path=str(bundle))
        assert n.is_valid("text/html; charset=utf-8") is True
        assert n.is_valid("application/json; version=1") is True


# ---------------------------------------------------------------------------
# Cache and refresh lifecycle
# ---------------------------------------------------------------------------


class TestCache:
    def test_uses_fresh_cache_over_bundle(self, mock_iana_data, tmp_path):
        """When a fresh (<30d) cached version exists, it wins over bundled."""
        bundle = _write_json(tmp_path / "bundle.json", mock_iana_data)
        cache_dir = tmp_path / "cache"

        fresh_data = {
            "_metadata": {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "source": "IANA",
                "count": 2,
            },
            "types": {
                "application/json": {
                    "name": "json",
                    "template": "application/json",
                    "reference": "RFC 8259",
                },
                "text/plain": {
                    "name": "plain",
                    "template": "text/plain",
                    "reference": "RFC 2046",
                },
            },
            "name_lookup": {
                "json": "application/json",
                "plain": "text/plain",
            },
        }
        _write_json(cache_dir / "iana_media_types.json", fresh_data)

        n = IANANormalizer(bundled_path=str(bundle), cache_dir=str(cache_dir))

        # The fresh cache lacks "text/csv" which the bundle has
        assert n.normalize("text/csv") == "text/csv"  # preserved — not in cache
        assert n.normalize("application/json") == "application/json"
        assert "csv" not in n.name_lookup

    def test_stale_cache_triggers_refresh(self, mock_iana_data, tmp_path):
        """Stale cache (>30d) triggers refresh; fresh data is used."""
        bundle = _write_json(tmp_path / "bundle.json", mock_iana_data)
        cache_dir = tmp_path / "cache"

        stale_data = {
            "_metadata": {
                "last_updated": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                "source": "IANA",
                "count": 1,
            },
            "types": {},
            "name_lookup": {},
        }
        _write_json(cache_dir / "iana_media_types.json", stale_data)

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status.return_value = None
        mock_response.text = MINIMAL_IANA_XML

        with patch("httpx.get", return_value=mock_response) as mock_get:
            n = IANANormalizer(bundled_path=str(bundle), cache_dir=str(cache_dir))

            mock_get.assert_called_once()
            assert n.normalize("application/json") == "application/json"
            assert n.normalize("application/xml") == "application/xml"
            assert n.normalize("application/zip") == "application/zip"

        # Verify the cache file was updated
        cached_json = json.loads((cache_dir / "iana_media_types.json").read_text())
        assert cached_json["_metadata"]["count"] == 3
        assert "application/json" in cached_json["types"]

    def test_refresh_failure_falls_back_to_bundled(self, mock_iana_data, tmp_path):
        """When refresh fails on stale cache, bundled data is used."""
        bundle = _write_json(tmp_path / "bundle.json", mock_iana_data)
        cache_dir = tmp_path / "cache"

        stale_data = {
            "_metadata": {
                "last_updated": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                "source": "IANA",
                "count": 1,
            },
            "types": {
                "text/plain": {
                    "name": "plain",
                    "template": "text/plain",
                    "reference": "RFC 2046",
                }
            },
            "name_lookup": {"plain": "text/plain"},
        }
        _write_json(cache_dir / "iana_media_types.json", stale_data)

        with patch("httpx.get", side_effect=httpx.ConnectError("no network")):
            n = IANANormalizer(bundled_path=str(bundle), cache_dir=str(cache_dir))

        # Falls back to bundle, so we have all the mock_iana_data types
        assert n.normalize("application/json") == "application/json"
        assert n.normalize("text/csv") == "text/csv"
        assert len(n.types) >= 7  # from the mock_iana_data fixture

    def test_explicit_refresh_success(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "bundle.json", mock_iana_data)
        cache_dir = tmp_path / "cache"

        n = IANANormalizer(bundled_path=str(bundle), cache_dir=str(cache_dir))

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status.return_value = None
        mock_response.text = MINIMAL_IANA_XML

        with patch("httpx.get", return_value=mock_response):
            result = n.refresh_data()

        assert result is True
        # Should have 3 types from MINIMAL_IANA_XML
        assert n.normalize("application/json") == "application/json"
        assert n.normalize("application/xml") == "application/xml"
        assert n.normalize("application/zip") == "application/zip"

    def test_explicit_refresh_failure(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "bundle.json", mock_iana_data)
        cache_dir = tmp_path / "cache"

        n = IANANormalizer(bundled_path=str(bundle), cache_dir=str(cache_dir))
        original_types = dict(n.types)

        with patch(
            "httpx.get",
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock()),
        ):
            result = n.refresh_data()

        assert result is False
        # In-memory data unchanged
        assert dict(n.types) == original_types

    def test_cache_directory_created(self, mock_iana_data, tmp_path):
        """Cache directory is auto-created on save."""
        bundle = _write_json(tmp_path / "bundle.json", mock_iana_data)
        cache_dir = tmp_path / "nonexistent" / "cache"

        n = IANANormalizer(bundled_path=str(bundle), cache_dir=str(cache_dir))

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status.return_value = None
        mock_response.text = MINIMAL_IANA_XML

        with patch("httpx.get", return_value=mock_response):
            n.refresh_data()

        assert cache_dir.is_dir()
        assert (cache_dir / "iana_media_types.json").is_file()


# ---------------------------------------------------------------------------
# Edge cases and failure modes
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_bundled_file_missing_graceful(self, tmp_path):
        """Missing bundled file → empty lookups, no crash."""
        n = IANANormalizer(
            bundled_path=str(tmp_path / "nonexistent.json"),
            cache_dir=str(tmp_path / "cache"),
        )
        assert n.types == {}
        assert n.name_lookup == {}
        assert n.normalize("text/html") == "text/html"
        assert n.is_valid("text/html") is False

    def test_bundled_file_corrupt_json(self, tmp_path):
        """Corrupt bundled JSON → empty lookups, no crash."""
        bad = tmp_path / "corrupt.json"
        bad.write_text("not valid json{{{", encoding="utf-8")
        n = IANANormalizer(
            bundled_path=str(bad),
            cache_dir=str(tmp_path / "cache"),
        )
        assert n.types == {}
        assert n.normalize("application/json") == "application/json"

    def test_no_cache_on_first_init(self, mock_iana_data, tmp_path):
        """No cache exists → use bundled data directly, no network call."""
        bundle = _write_json(tmp_path / "bundle.json", mock_iana_data)
        cache_dir = tmp_path / "empty_cache"

        with patch("httpx.get") as mock_get:
            n = IANANormalizer(bundled_path=str(bundle), cache_dir=str(cache_dir))
            mock_get.assert_not_called()

        assert n.normalize("application/json") == "application/json"
        assert len(n.types) == len(mock_iana_data["types"])

    def test_name_lookup_ambiguous_skipped(self, tmp_path):
        """When a short name maps to multiple types, it's excluded from name_lookup."""
        # Build data where "rdf" maps to both application/rdf and text/rdf
        data = {
            "_metadata": {
                "last_updated": "2026-01-01T00:00:00Z",
                "source": "test",
                "count": 2,
            },
            "types": {
                "application/rdf+xml": {
                    "name": "rdf+xml",
                    "template": "application/rdf+xml",
                    "reference": "",
                },
                "text/rdf": {"name": "rdf", "template": "text/rdf", "reference": ""},
            },
            "name_lookup": {
                "rdf+xml": "application/rdf+xml",
                # "rdf" is intentionally absent — ambiguous
            },
        }
        bundle = _write_json(tmp_path / "bundle.json", data)
        n = IANANormalizer(bundled_path=str(bundle))

        # rdf+xml is unambiguous → should resolve
        assert n.normalize("rdf+xml") == "application/rdf+xml"
        # "rdf" is ambiguous → not in name_lookup → preserved as-is
        assert n.normalize("rdf") == "rdf"

    def test_cached_file_corrupt_falls_back(self, mock_iana_data, tmp_path):
        bundle = _write_json(tmp_path / "bundle.json", mock_iana_data)
        cache_dir = tmp_path / "cache"
        (cache_dir / "iana_media_types.json").parent.mkdir(parents=True, exist_ok=True)
        (cache_dir / "iana_media_types.json").write_text("garbage", encoding="utf-8")

        n = IANANormalizer(bundled_path=str(bundle), cache_dir=str(cache_dir))
        assert n.normalize("application/json") == "application/json"
