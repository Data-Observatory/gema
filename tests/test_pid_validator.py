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
            ("ORCID", "0000-0002-1825-0097", True),  # real ORCID iD
            ("orcid", "https://orcid.org/0000-0002-1825-0097", True),
            ("ORCID", "0000-0002-1825-0098", False),  # wrong check digit
            ("ORCID", "not-an-orcid", False),
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

    def test_orcid_normalized_strips_url_prefix(self) -> None:
        _, normalized = validate_pid_format("ORCID", "https://orcid.org/0000-0002-1825-0097")
        assert normalized == "0000-0002-1825-0097"


class TestExtractPids:
    def test_finds_ror_in_creator_identifier(self) -> None:
        output = {
            "schema:creator": [
                {"schema:identifier": [{"propertyID": "ROR", "value": "https://ror.org/02sevrz47"}]}
            ]
        }
        triples = extract_pids(output)
        assert (
            "ROR",
            "https://ror.org/02sevrz47",
            "root.schema:creator[0].schema:identifier[0]",
        ) in triples

    def test_finds_orcid_in_creator_identifier(self) -> None:
        output = {
            "schema:creator": [
                {"schema:identifier": [{"propertyID": "ORCID", "value": "0000-0002-1825-0097"}]}
            ]
        }
        triples = extract_pids(output)
        assert (
            "ORCID",
            "0000-0002-1825-0097",
            "root.schema:creator[0].schema:identifier[0]",
        ) in triples

    def test_finds_isni_in_affiliation(self) -> None:
        output = {
            "schema:creator": [
                {
                    "schema:affiliation": [
                        {"schema:identifier": [{"propertyID": "ISNI", "value": "000000040628717X"}]}
                    ]
                }
            ]
        }
        triples = extract_pids(output)
        assert triples == [
            (
                "ISNI",
                "000000040628717X",
                "root.schema:creator[0].schema:affiliation[0].schema:identifier[0]",
            )
        ]

    def test_finds_ror_in_publisher(self) -> None:
        output = {
            "schema:publisher": {
                "schema:identifier": [{"propertyID": "ROR", "value": "https://ror.org/02sevrz47"}]
            }
        }
        assert extract_pids(output) == [
            ("ROR", "https://ror.org/02sevrz47", "root.schema:publisher.schema:identifier[0]")
        ]

    def test_finds_ror_in_funder_identifiers(self) -> None:
        output = {
            "schema:funding": [
                {
                    "funder": {
                        "schema:identifier": [
                            {"propertyID": "ROR", "value": "https://ror.org/02sevrz47"}
                        ]
                    }
                }
            ]
        }
        triples = extract_pids(output)
        assert (
            "ROR",
            "https://ror.org/02sevrz47",
            "root.schema:funding[0].funder.schema:identifier[0]",
        ) in triples

    def test_finds_doi_in_top_level_identifier(self) -> None:
        output = {"schema:identifier": [{"propertyID": "DOI", "value": "10.5281/zenodo.1234567"}]}
        assert extract_pids(output) == [
            ("DOI", "10.5281/zenodo.1234567", "root.schema:identifier[0]")
        ]

    def test_non_pid_scheme_extracted_but_filtered_downstream(self) -> None:
        """extract_pids returns every propertyID/value pair regardless of
        scheme (same generic walk as ROR/ORCID/etc.) -- unknown schemes
        like a bare "URL" tag are filtered later by validate_pids's
        _KNOWN_SCHEMES check, not here (see TestValidatePids.test_unknown_scheme_ignored)."""
        output = {"schema:identifier": [{"propertyID": "URL", "value": "https://example.com/x"}]}
        assert extract_pids(output) == [("URL", "https://example.com/x", "root.schema:identifier[0]")]

    def test_finds_doi_in_same_as(self) -> None:
        output = {"schema:sameAs": [{"value": "https://doi.org/10.5281/zenodo.1234567"}]}
        assert extract_pids(output) == [
            ("DOI", "https://doi.org/10.5281/zenodo.1234567", "schema:sameAs[0]")
        ]

    def test_finds_doi_in_related_link(self) -> None:
        output = {
            "schema:relatedLink": [
                {"target": {"url": "https://doi.org/10.5281/zenodo.1234567"}, "url": "https://doi.org/10.5281/zenodo.1234567"}
            ]
        }
        assert extract_pids(output) == [
            ("DOI", "https://doi.org/10.5281/zenodo.1234567", "schema:relatedLink[0]")
        ]

    def test_empty_output_returns_empty(self) -> None:
        assert extract_pids({}) == []

    def test_blank_identifier_ignored(self) -> None:
        output = {"schema:publisher": {"schema:identifier": [{"propertyID": "ROR", "value": ""}]}}
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

    def test_orcid_resolves_no_auth_needed(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=200)
        assert resolve_pid(client, "ORCID", "0000-0002-1825-0097") is True
        client.get.assert_called_once_with(
            "https://orcid.org/0000-0002-1825-0097",
            headers={"Accept": "application/orcid+json"},
            follow_redirects=True,
            timeout=15.0,
        )

    def test_orcid_url_form_strips_prefix_before_request(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=200)
        resolve_pid(client, "ORCID", "https://orcid.org/0000-0002-1825-0097")
        assert client.get.call_args[0][0] == "https://orcid.org/0000-0002-1825-0097"

    def test_orcid_not_found(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=404)
        assert resolve_pid(client, "ORCID", "0000-0002-1825-0097") is False


class TestValidatePids:
    def test_no_pids_returns_empty(self) -> None:
        assert validate_pids({}, resolve=False) == []

    def test_format_only_no_network(self) -> None:
        output = {"schema:publisher": {"schema:identifier": [{"propertyID": "ROR", "value": "https://ror.org/BADID"}]}}
        checks = validate_pids(output, resolve=False)
        assert len(checks) == 1
        assert checks[0].format_ok is False
        assert checks[0].resolved is None
        assert checks[0].problem is not None

    def test_malformed_pid_skips_live_resolve(self) -> None:
        client = MagicMock(spec=httpx.Client)
        output = {"schema:publisher": {"schema:identifier": [{"propertyID": "ROR", "value": "https://ror.org/BADID"}]}}
        validate_pids(output, resolve=True, client=client)
        assert not client.get.called

    def test_well_formed_pid_triggers_live_resolve(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=200)
        output = {"schema:publisher": {"schema:identifier": [{"propertyID": "ROR", "value": "https://ror.org/02sevrz47"}]}}
        checks = validate_pids(output, resolve=True, client=client)
        assert checks[0].resolved is True
        assert checks[0].problem is None

    def test_resolve_false_that_produces_a_problem(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=404)
        output = {"schema:publisher": {"schema:identifier": [{"propertyID": "ROR", "value": "https://ror.org/02sevrz47"}]}}
        checks = validate_pids(output, resolve=True, client=client)
        assert checks[0].resolved is False
        assert checks[0].problem is not None

    def test_unknown_scheme_ignored(self) -> None:
        output = {"schema:publisher": {"schema:identifier": [{"propertyID": "GRID", "value": "12345"}]}}
        assert validate_pids(output, resolve=False) == []

    def test_orcid_checked_end_to_end_no_credentials_needed(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.return_value = MagicMock(status_code=200)
        output = {
            "schema:creator": [
                {"schema:identifier": [{"propertyID": "ORCID", "value": "0000-0002-1825-0097"}]}
            ]
        }
        checks = validate_pids(output, resolve=True, client=client)
        assert len(checks) == 1
        assert checks[0].scheme == "ORCID"
        assert checks[0].format_ok is True
        assert checks[0].resolved is True
        assert checks[0].problem is None
