"""Tests for enrichers.pid_validator."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from metadata_enricher.enrichers.pid_validator import (
    extract_pids,
    resolve_pid,
    validate_pid_format,
    validate_pids,
)


class TestValidatePidFormat:
    @pytest.mark.parametrize(
        "scheme,value,expected_ok",
        [
            ("DOI", "10.5281/zenodo.1234567", True),
            ("DOI", "https://doi.org/10.5281/zenodo.1234567", True),
            ("doi", "not-a-doi", False),
            ("ROR", "https://ror.org/02sevrz47", True),
            ("ROR", "https://ror.org/BADID", False),
            ("ISNI", "0000000121032683", True),  # real ISNI: Stanford University
            ("ISNI", "000000012103268X", False),  # wrong check digit
            ("ISNI", "0000 0001 2103 2683", True),
            ("UNKNOWN", "anything", True),  # unrecognized scheme — not our concern
        ],
    )
    def test_format_check(self, scheme: str, value: str, expected_ok: bool) -> None:
        ok, _ = validate_pid_format(scheme, value)
        assert ok is expected_ok

    def test_doi_normalized_strips_url_prefix(self) -> None:
        _, normalized = validate_pid_format("DOI", "https://doi.org/10.1/x")
        assert normalized == "10.1/x"

    def test_isni_normalized_strips_spaces(self) -> None:
        _, normalized = validate_pid_format("ISNI", "0000 0001 2103 2683")
        assert normalized == "0000000121032683"


class TestExtractPids:
    def test_finds_ror_in_creator_name_identifiers(self) -> None:
        output = {
            "creators": [
                {"name_identifiers": [{"name_identifier": "https://ror.org/02sevrz47", "name_identifier_scheme": "ROR"}]}
            ]
        }
        triples = extract_pids(output)
        assert ("ROR", "https://ror.org/02sevrz47", "root.creators[0].name_identifiers[0]") in triples

    def test_finds_isni_in_affiliation(self) -> None:
        output = {
            "creators": [{"affiliations": [{"affiliation_identifier": "000000040628717X", "affiliation_identifier_scheme": "ISNI"}]}]
        }
        triples = extract_pids(output)
        assert triples == [("ISNI", "000000040628717X", "root.creators[0].affiliations[0]")]

    def test_finds_ror_in_publisher(self) -> None:
        output = {"publishers": [{"publisher_identifier": "https://ror.org/02sevrz47", "publisher_identifier_scheme": "ROR"}]}
        assert extract_pids(output) == [("ROR", "https://ror.org/02sevrz47", "root.publishers[0]")]

    def test_finds_ror_in_funder_identifiers(self) -> None:
        output = {
            "funding_references": [
                {"funder_identifiers": [{"funder_identifier": "https://ror.org/02sevrz47", "funder_identifier_type": "ROR"}]}
            ]
        }
        triples = extract_pids(output)
        assert ("ROR", "https://ror.org/02sevrz47", "root.funding_references[0].funder_identifiers[0]") in triples

    def test_finds_doi_in_resource_identifier(self) -> None:
        output = {"resource": {"identifier": "10.5281/zenodo.1234567", "identifier_type": "DOI"}}
        assert extract_pids(output) == [("DOI", "10.5281/zenodo.1234567", "resource.identifier")]

    def test_ignores_non_doi_resource_identifier(self) -> None:
        output = {"resource": {"identifier": "https://example.com/x", "identifier_type": "URL"}}
        assert extract_pids(output) == []

    def test_finds_doi_in_related_identifiers(self) -> None:
        output = {
            "related_identifiers": [
                {"related_identifier": "10.5281/zenodo.1234567", "related_identifier_type": "DOI"}
            ]
        }
        assert extract_pids(output) == [
            ("DOI", "10.5281/zenodo.1234567", "related_identifiers[0].related_identifier")
        ]

    def test_finds_doi_in_alternate_identifiers(self) -> None:
        output = {
            "alternate_identifiers": [
                {"alternate_identifier": "10.5281/zenodo.1234567", "alternate_identifier_type": "DOI"}
            ]
        }
        assert extract_pids(output) == [
            ("DOI", "10.5281/zenodo.1234567", "alternate_identifiers[0].alternate_identifier")
        ]

    def test_empty_output_returns_empty(self) -> None:
        assert extract_pids({}) == []

    def test_blank_identifier_ignored(self) -> None:
        output = {"publishers": [{"publisher_identifier": "", "publisher_identifier_scheme": "ROR"}]}
        assert extract_pids(output) == []


class TestResolvePid:
    def test_doi_resolves(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=200)
        assert resolve_pid(client, "DOI", "10.5281/zenodo.1234567") is True

    def test_ror_not_found(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=404)
        assert resolve_pid(client, "ROR", "https://ror.org/02sevrz47") is False

    def test_isni_403_is_inconclusive_not_a_failure(self) -> None:
        """isni.org 403s automated lookups of otherwise-valid ISNIs — must not
        read as 'does not resolve' (observed live, see pid_validator.py)."""
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=403)
        assert resolve_pid(client, "ISNI", "0000000121032683") is None

    def test_ror_429_rate_limited_is_inconclusive(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=429)
        assert resolve_pid(client, "ROR", "https://ror.org/02sevrz47") is None

    def test_doi_5xx_is_inconclusive(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=503)
        assert resolve_pid(client, "DOI", "10.5281/zenodo.1234567") is None

    def test_network_error_returns_none(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.HTTPError("boom")
        assert resolve_pid(client, "ISNI", "0000000121032683") is None


class TestValidatePids:
    def test_no_pids_returns_empty(self) -> None:
        assert validate_pids({}, resolve=False) == []

    def test_format_only_no_network(self) -> None:
        output = {"publishers": [{"publisher_identifier": "https://ror.org/BADID", "publisher_identifier_scheme": "ROR"}]}
        checks = validate_pids(output, resolve=False)
        assert len(checks) == 1
        assert checks[0].format_ok is False
        assert checks[0].resolved is None
        assert checks[0].problem is not None

    def test_malformed_pid_skips_live_resolve(self) -> None:
        client = MagicMock(spec=httpx.Client)
        output = {"publishers": [{"publisher_identifier": "https://ror.org/BADID", "publisher_identifier_scheme": "ROR"}]}
        validate_pids(output, resolve=True, client=client)
        assert not client.get.called

    def test_well_formed_pid_triggers_live_resolve(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=200)
        output = {"publishers": [{"publisher_identifier": "https://ror.org/02sevrz47", "publisher_identifier_scheme": "ROR"}]}
        checks = validate_pids(output, resolve=True, client=client)
        assert checks[0].resolved is True
        assert checks[0].problem is None

    def test_resolve_false_that_produces_a_problem(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=404)
        output = {"publishers": [{"publisher_identifier": "https://ror.org/02sevrz47", "publisher_identifier_scheme": "ROR"}]}
        checks = validate_pids(output, resolve=True, client=client)
        assert checks[0].resolved is False
        assert checks[0].problem is not None

    def test_unknown_scheme_ignored(self) -> None:
        output = {"publishers": [{"publisher_identifier": "12345", "publisher_identifier_scheme": "GRID"}]}
        assert validate_pids(output, resolve=False) == []
