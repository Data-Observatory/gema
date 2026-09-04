"""Tests for the vendored CDIF Discovery artifacts (metadata_enricher.schemas.cdif.discovery).

Sanity checks on committed bytes only -- never polls upstream. Re-vendoring is
manual and maintainer-declared (docs/codata_mcp_croissant_cdifspecs.md sec 6.2).
"""

from __future__ import annotations

import json
import re
from importlib import resources

import pytest

_PACKAGE = "metadata_enricher.schemas.cdif.discovery"


def _read(name: str) -> str:
    return (resources.files(_PACKAGE) / name).read_text(encoding="utf-8")


def _read_bytes(name: str) -> bytes:
    return (resources.files(_PACKAGE) / name).read_bytes()


class TestFilesExist:
    def test_schema_json_exists(self) -> None:
        assert _read("schema.json")

    def test_frame_jsonld_exists(self) -> None:
        assert _read("frame.jsonld")

    def test_shacl_ttl_exists(self) -> None:
        assert _read("shacl.ttl")

    def test_vendored_sha_txt_exists(self) -> None:
        assert _read("VENDORED_SHA.txt")

    def test_crosswalk_xlsx_exists_and_is_a_real_xlsx(self) -> None:
        """crosswalk.xlsx is reference material (CDIF's own DataCite<->schema.org
        crosswalk) consumed by humans writing docs/cdif_pivot_implementation_plan.md,
        not by any code -- just check it's really an xlsx (zip magic bytes), no
        openpyxl dependency needed for that."""
        assert _read_bytes("crosswalk.xlsx").startswith(b"PK\x03\x04")


class TestParsing:
    def test_schema_json_parses(self) -> None:
        assert isinstance(json.loads(_read("schema.json")), dict)

    def test_frame_jsonld_parses(self) -> None:
        assert isinstance(json.loads(_read("frame.jsonld")), dict)

    def test_shacl_ttl_is_non_empty_text(self) -> None:
        content = _read("shacl.ttl")
        assert len(content) > 100
        assert "@prefix" in content or "PREFIX" in content


class TestVendoredShaFile:
    def test_contains_a_commit_sha(self) -> None:
        content = _read("VENDORED_SHA.txt")
        match = re.search(r"commit_sha=([0-9a-f]{40})", content)
        assert match is not None, "VENDORED_SHA.txt must record a 40-char commit SHA"

    def test_contains_source_repo_url(self) -> None:
        content = _read("VENDORED_SHA.txt")
        assert "github.com/Cross-Domain-Interoperability-Framework" in content


class TestOpenWorldShape:
    """The validation argument in spec sec 3.2 depends on CDIF's schema being
    open-world (no closed top-level shape) -- if a future re-vendor tightens
    this, that argument breaks silently unless this test catches it."""

    @pytest.fixture
    def schema(self) -> dict[str, object]:
        return json.loads(_read("schema.json"))

    def test_no_closed_top_level_additional_properties(self, schema: dict[str, object]) -> None:
        assert schema.get("additionalProperties") is not False

    def test_no_flat_top_level_required_list(self, schema: dict[str, object]) -> None:
        assert "required" not in schema

    def test_required_floor_lives_in_allof_not_flat_required(
        self, schema: dict[str, object]
    ) -> None:
        """The real schema enforces the required floor via allOf[0].required plus
        two anyOf conditional groups, not a flat top-level `required` list."""
        all_of = schema.get("allOf")
        assert isinstance(all_of, list) and all_of
        floor = all_of[0].get("required")
        assert floor is not None
        for field in (
            "@id",
            "@type",
            "@context",
            "schema:name",
            "schema:identifier",
            "schema:dateModified",
            "schema:subjectOf",
        ):
            assert field in floor
