"""Tests for CDIFDiscoveryProfile.check_shacl_conformance.

See docs/codata_mcp_croissant_cdifspecs.md Appendix B Q5 for the decision
behind these tests (why the vendored shapes flag every real
recorded golden fixture as non-conformant today, and why that's a genuine
gap in what gema currently emits rather than a JSON-LD-conversion bug --
that class of false positive was Step 5.5's bug, already fixed).

The "conformant" fixture below was built by hand and iteratively checked
against the real vendored ``shacl.ttl`` (not asserted to be conformant on
faith) -- it deliberately satisfies every ``sh:Violation``-severity shape
targeting a root ``schema:Dataset`` node and its ``schema:subjectOf``
CatalogRecord node, including two easy-to-miss details found only by
running the real shapes: ``schema:keywords`` entries need a
``schema:name`` of at least 3 characters (``cdifd:termLabelProperty``),
and ``schema:subjectOf.dcterms:conformsTo`` must carry *both*
``https://w3id.org/cdif/core/1.0`` and ``.../cdif/discovery/1.0`` (CDIF's
own shapes require both URIs -- ``CDIFDiscoveryProfile`` now emits both,
Open Question #18, resolved; this fixture always carried both, since it
was written ahead of that fix).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from metadata_enricher.schemas.cdif.discovery.cdif_discovery import CDIFDiscoveryProfile
from metadata_enricher.types import MetadataDocument

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden" / "expected"
GOLDEN_FIXTURES = sorted(GOLDEN_DIR.glob("sample_input0*.json"))


@pytest.fixture
def schema() -> CDIFDiscoveryProfile:
    return CDIFDiscoveryProfile()


def _doc_from(fields: dict) -> MetadataDocument:
    doc = MetadataDocument()
    for key, value in fields.items():
        doc.set_field(key, value)
    return doc


# A hand-built, real-shapes-verified conformant CDIF Discovery document --
# satisfies every sh:Violation-severity shape in the vendored shacl.ttl
# that applies to a root schema:Dataset node (resourceIdentifierProperty,
# nameProperty, rightsProperty, dateModifiedProperty, accessProperty,
# CDIFDefinedTermShape via schema:keywords) and to its schema:subjectOf
# CatalogRecord node (metadataProfileProperty, metadataSubjectProperty).
CONFORMANT_FIELDS: dict = {
    "@context": {
        "schema": "http://schema.org/",
        "dcterms": "http://purl.org/dc/terms/",
        "dcat": "http://www.w3.org/ns/dcat#",
        "prov": "http://www.w3.org/ns/prov#",
        "dqv": "http://www.w3.org/ns/dqv#",
    },
    "@id": "https://example.org/dataset/1",
    "@type": ["schema:Dataset"],
    "schema:name": "A fully conformant test dataset",
    "schema:description": "A description.",
    "schema:datePublished": "2026-01-01",
    "schema:identifier": [
        {
            "@type": ["schema:PropertyValue"],
            "schema:propertyID": "DOI",
            "schema:value": "10.1/xyz",
            "schema:url": "https://doi.org/10.1/xyz",
        }
    ],
    "schema:dateModified": "2026-09-04",
    "schema:license": [{"@id": "https://creativecommons.org/licenses/by/4.0/"}],
    "schema:url": "https://example.org/dataset/1",
    "schema:creator": [{"@type": ["schema:Organization"], "schema:name": "Some Org"}],
    "schema:keywords": [{"@type": ["schema:DefinedTerm"], "schema:name": "a keyword term"}],
    "schema:subjectOf": {
        "@id": "https://example.org/dataset/1#metadata",
        "@type": ["schema:Dataset"],
        "schema:additionalType": ["dcat:CatalogRecord"],
        "schema:about": {"@id": "https://example.org/dataset/1"},
        "dcterms:conformsTo": [
            {"@id": "https://w3id.org/cdif/core/1.0"},
            {"@id": "https://w3id.org/cdif/discovery/1.0"},
        ],
    },
}


class TestCheckShaclConformance:
    def test_conformant_document_produces_no_violations(self, schema: CDIFDiscoveryProfile) -> None:
        doc = _doc_from(CONFORMANT_FIELDS)
        assert schema.check_shacl_conformance(doc) == []

    def test_missing_required_field_produces_a_real_violation(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        fields = copy.deepcopy(CONFORMANT_FIELDS)
        del fields["schema:license"]
        doc = _doc_from(fields)

        violations = schema.check_shacl_conformance(doc)

        assert len(violations) == 1
        assert "license" in violations[0] or "rights" in violations[0].lower()
        assert "rightsProperty" in violations[0]

    def test_missing_both_or_groups_produces_two_violations(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        fields = copy.deepcopy(CONFORMANT_FIELDS)
        del fields["schema:license"]
        del fields["schema:url"]
        doc = _doc_from(fields)

        violations = schema.check_shacl_conformance(doc)

        assert any("rightsProperty" in v for v in violations)
        assert any("accessProperty" in v for v in violations)

    def test_malformed_input_never_raises(self, schema: CDIFDiscoveryProfile) -> None:
        doc = MetadataDocument()
        doc.set_field("schema:name", 12345)
        doc.set_field("@type", "not-a-list-or-dict")
        doc.set_field("schema:identifier", "just a string")
        # Should never raise -- degrades to an empty list plus a logged warning.
        assert schema.check_shacl_conformance(doc) == []

    def test_empty_document_never_raises(self, schema: CDIFDiscoveryProfile) -> None:
        assert schema.check_shacl_conformance(MetadataDocument()) == []

    def test_document_with_no_type_produces_no_violations_target_not_matched(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        """A document with no @type: ["schema:Dataset"] triple doesn't match
        the vendored shapes' SPARQLTarget at all -- zero violations here
        means "nothing was evaluated", not "conformant". Documents this
        real, non-obvious edge case rather than let it look like a false
        conformance claim."""
        doc = _doc_from({"schema:name": "T"})
        assert schema.check_shacl_conformance(doc) == []

    @pytest.mark.parametrize("fixture_path", GOLDEN_FIXTURES, ids=lambda p: p.stem)
    def test_real_golden_fixtures_produce_sensible_not_nonsensical_violations(
        self, schema: CDIFDiscoveryProfile, fixture_path: Path
    ) -> None:
        """Every real recorded golden fixture is expected to fail this
        check today (see module-level docstring and
        docs/codata_mcp_croissant_cdifspecs.md Appendix B Q5/Q16) -- this
        test isn't asserting conformance, it's asserting the
        failures are *real* and *explicable* (missing @type typing on
        nested identifier/license nodes, or genuinely absent license/url/
        distribution data), never an empty violations list masking a check
        that silently didn't run, and never a violation whose focus
        node/shape is nonsensical."""
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        doc = _doc_from(raw)

        violations = schema.check_shacl_conformance(doc)

        assert len(violations) > 0, (
            f"{fixture_path.name}: expected real SHACL violations (every fixture's "
            "top-level schema:identifier entries carry no @type, failing "
            "resourceIdentifierProperty's sh:class check) -- an empty list here "
            "would mean the check silently didn't run"
        )
        # Every fixture's top-level schema:identifier entries lack an
        # explicit @type (schema:PropertyValue) -- a real, still-open gap
        # (Open Question #16 only fixed *nested* Person/Organization/
        # MonetaryGrant identifier cardinality, not @type on any
        # identifier entry, nested or top-level). This is the one
        # violation guaranteed across every fixture since Open Question
        # #18 fixed the previously-guaranteed conformsTo gap; the rest
        # vary by what real content each fixture happens to carry.
        assert any("resourceIdentifierProperty" in v for v in violations)
        for violation in violations:
            assert violation.strip()
            assert "shape=" in violation

