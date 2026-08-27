"""Tests for scripts/do_catalog_common.py's scheme-aware identifier scoring.

scripts/ has no package __init__.py and isn't on pythonpath (only src/ is,
per pyproject.toml) -- other scripts rely on being executed with scripts/
itself as cwd/sys.path[0]. Insert it explicitly here instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

_scripts = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from do_catalog_common import extract_identifiers, identifier_match_score  # noqa: E402


class TestExtractIdentifiersISNINormalization:
    """Ground truth wraps ISNI in a resolver URL; the pipeline emits bare
    digits (identifier_enricher.py) -- both must normalize to the same
    (scheme, value) pair."""

    def test_uri_wrapped_and_bare_isni_match(self) -> None:
        truth = {
            "creators": [
                {
                    "name_identifiers": [
                        {
                            "name_identifier": "https://isni.org/isni/0000000122238173",
                            "name_identifier_scheme": "ISNI",
                        }
                    ]
                }
            ]
        }
        actual = {
            "creators": [
                {
                    "name_identifiers": [
                        {"name_identifier": "0000000122238173", "name_identifier_scheme": "ISNI"}
                    ]
                }
            ]
        }
        schemes = frozenset({"ISNI"})
        assert extract_identifiers(truth, schemes) == extract_identifiers(actual, schemes)
        assert identifier_match_score(truth, actual, schemes) == 1.0

    def test_isni_with_spaces_normalizes_same_as_compact(self) -> None:
        truth = {
            "publishers": [
                {
                    "publisher_identifier": "0000 0001 2223 8173",
                    "publisher_identifier_scheme": "ISNI",
                }
            ]
        }
        actual = {
            "publishers": [
                {
                    "publisher_identifier": "0000000122238173",
                    "publisher_identifier_scheme": "ISNI",
                }
            ]
        }
        schemes = frozenset({"ISNI"})
        assert extract_identifiers(truth, schemes) == extract_identifiers(actual, schemes)


class TestExtractIdentifiersRORNormalization:
    """ROR is URI-wrapped on both sides but truth/output could still differ
    on trailing slash or case."""

    def test_ror_url_and_bare_path_match(self) -> None:
        truth = {
            "creators": [
                {
                    "affiliations": [
                        {
                            "affiliation_identifier": "https://ror.org/047gc3g35",
                            "affiliation_identifier_scheme": "ROR",
                        }
                    ]
                }
            ]
        }
        actual = {
            "creators": [
                {
                    "affiliations": [
                        {
                            "affiliation_identifier": "047gc3g35",
                            "affiliation_identifier_scheme": "ROR",
                        }
                    ]
                }
            ]
        }
        schemes = frozenset({"ROR"})
        assert extract_identifiers(truth, schemes) == extract_identifiers(actual, schemes)


class TestExtractIdentifiersORCIDNormalization:
    def test_orcid_url_and_bare_id_match(self) -> None:
        truth = {
            "creators": [
                {
                    "name_identifiers": [
                        {
                            "name_identifier": "https://orcid.org/0000-0002-1825-0097",
                            "name_identifier_scheme": "ORCID",
                        }
                    ]
                }
            ]
        }
        actual = {
            "creators": [
                {
                    "name_identifiers": [
                        {
                            "name_identifier": "0000-0002-1825-0097",
                            "name_identifier_scheme": "ORCID",
                        }
                    ]
                }
            ]
        }
        schemes = frozenset({"ORCID"})
        assert extract_identifiers(truth, schemes) == extract_identifiers(actual, schemes)


class TestExtractIdentifiersUnaffectedSchemes:
    """VIAF/Wikidata never appear on the pipeline side -- normalization must
    stay a no-op (beyond strip/lowercase) for them."""

    def test_viaf_only_strip_lowercase(self) -> None:
        attrs = {
            "publishers": [
                {"publisher_identifier": " VIAF123 ", "publisher_identifier_scheme": "VIAF"}
            ]
        }
        assert extract_identifiers(attrs, frozenset({"VIAF"})) == {("VIAF", "viaf123")}


class TestIdentifierMatchScore:
    def test_no_truth_no_actual_is_perfect(self) -> None:
        assert identifier_match_score({}, {}, frozenset({"ROR"})) == 1.0

    def test_actual_hallucinates_when_truth_empty(self) -> None:
        actual = {
            "publishers": [
                {"publisher_identifier": "https://ror.org/abc", "publisher_identifier_scheme": "ROR"}
            ]
        }
        assert identifier_match_score({}, actual, frozenset({"ROR"})) == 0.0
