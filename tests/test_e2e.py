"""End-to-end pipeline tests for the full merger enrichment flow (ROR + IANA).

All external calls are mocked.  No real ROR API calls, no real LLM calls.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from merger import MetadataMerger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def merger():
    return MetadataMerger()


def _ror_result(ror_id, name, country_code="CL"):
    """Shorthand for a resolved ROR entry."""
    return {"id": ror_id, "name": name, "country_code": country_code}


def _mock_ror_resolver(return_value):
    """Create a MagicMock for RORResolver with the given resolve_batch return."""
    mock = MagicMock()
    mock.resolve_batch.return_value = return_value
    return mock


def _mock_country_extractor(country_code="CL"):
    """Create a MagicMock for CountryExtractor with the given country."""
    mock = MagicMock()
    mock.extract_country.return_value = country_code
    return mock


# ---------------------------------------------------------------------------
# Test 1 — Full pipeline: ROR enrichment + IANA normalization together
# ---------------------------------------------------------------------------


def test_full_pipeline_ror_and_iana(merger):
    """Merge with publisher needing ROR + media_files with messy format string.

    Mock ROR API returns known result.  Verify output contains:
    - ROR ID injected into publishers
    - Normalised format string in media_files
    """
    agent_outputs = {
        "publisher_agent": {
            "publishers": [{"publisher_name": "Ministerio de Hacienda"}],
        },
        "media_agent": {
            "titles": [{"name": "Gastos municipales", "title_type": "MainTitle"}],
            "media_files": [
                {
                    "format": " Application/PDF ",
                    "file_uri": "https://datos.gob.cl/dataset/gastos.csv",
                }
            ],
        },
    }

    input_data = {
        "url": "https://datos.gob.cl/dataset/gastos-municipales",
        "publisher": "Ministerio de Hacienda",
    }

    mock_ror = _mock_ror_resolver(
        {
            "Ministerio de Hacienda": _ror_result(
                "https://ror.org/01h6h5x94", "Ministerio de Hacienda"
            ),
        }
    )
    mock_country = _mock_country_extractor("CL")

    with (
        patch("merger.RORResolver", return_value=mock_ror),
        patch("merger.CountryExtractor", return_value=mock_country),
    ):
        result = merger.merge(agent_outputs, input_data)

    attrs = result["attributes"]

    # Publishers: should have ROR ID injected
    pubs = attrs["publishers"]
    assert len(pubs) == 1
    assert pubs[0]["publisher_name"] == "Ministerio de Hacienda"
    assert pubs[0]["publisher_identifier"] == "https://ror.org/01h6h5x94"
    assert pubs[0]["publisher_identifier_scheme"] == "ROR"
    assert pubs[0]["publisher_scheme_uri"] == "https://ror.org"

    # Media files: format should be normalised
    media = attrs["media_files"]
    assert len(media) == 1
    assert media[0]["format"] == "application/pdf"


# ---------------------------------------------------------------------------
# Test 2 — Network failure: pipeline completes without ROR enrichment
# ---------------------------------------------------------------------------


def test_full_pipeline_network_failure_graceful(merger):
    """Merge when httpx raises ConnectTimeout — pipeline completes without ROR IDs.

    Mock httpx.get to raise httpx.ConnectTimeout.  The merger must catch
    the error gracefully and produce output without ROR enrichment.
    """
    agent_outputs = {
        "agent_a": {
            "titles": [{"name": "Dataset sin ROR", "title_type": "MainTitle"}],
            "publishers": [{"publisher_name": "Ministerio de Hacienda"}],
            "creators": [
                {
                    "creator_name": "Ministerio de Hacienda",
                    "creator_name_type": "Organizational",
                    "given_name": "",
                    "family_name": "",
                    "type": "Organization",
                    "name_identifiers": [],
                    "affiliations": [],
                }
            ],
        }
    }

    input_data = {
        "url": "https://datos.gob.cl/dataset/test",
        "publisher": "Ministerio de Hacienda",
    }

    # CountryExtractor still works — only the ROR network is down
    mock_country = _mock_country_extractor("CL")

    with (
        patch("merger.CountryExtractor", return_value=mock_country),
        patch(
            "httpx.get",
            side_effect=httpx.ConnectTimeout("Connection timed out"),
        ),
    ):
        result = merger.merge(agent_outputs, input_data)

    attrs = result["attributes"]

    # Pipeline completed — required fields present
    assert "titles" in attrs
    assert len(attrs["titles"]) == 1
    assert attrs["titles"][0]["name"] == "Dataset sin ROR"

    # Publishers exist but no ROR identifier (enrichment skipped gracefully)
    assert "publishers" in attrs
    pub = attrs["publishers"][0]
    assert pub["publisher_name"] == "Ministerio de Hacienda"
    assert "publisher_identifier" not in pub

    # Creators also exist without ROR
    assert "creators" in attrs
    creator = attrs["creators"][0]
    assert creator["creator_name"] == "Ministerio de Hacienda"
    assert creator["name_identifiers"] == []


# ---------------------------------------------------------------------------
# Test 3 — Different institution: "Data Observatory"
# ---------------------------------------------------------------------------


def test_full_pipeline_different_institution(merger):
    """Merge with a different institution ("Data Observatory") and verify ROR
    resolution works for institutions beyond the default fixture."""
    agent_outputs = {
        "agent_a": {
            "titles": [
                {"name": "Observaciones astronómicas", "title_type": "MainTitle"}
            ],
            "publishers": [{"publisher_name": "Data Observatory"}],
            "creators": [
                {
                    "creator_name": "Data Observatory",
                    "creator_name_type": "Organizational",
                    "given_name": "",
                    "family_name": "",
                    "type": "Organization",
                    "name_identifiers": [],
                    "affiliations": [],
                }
            ],
            "funding_references": [
                {
                    "funder_name": "Data Observatory",
                    "funding_stream": "",
                    "award_number": "",
                    "award_uri": "",
                    "award_title": "",
                    "funder_identifiers": [],
                }
            ],
        }
    }

    input_data = {
        "url": "https://dataobservatory.cl/dataset/astro",
        "publisher": "Data Observatory",
    }

    mock_ror = _mock_ror_resolver(
        {
            "Data Observatory": _ror_result(
                "https://ror.org/05m33x406", "Data Observatory"
            ),
        }
    )
    mock_country = _mock_country_extractor("CL")

    with (
        patch("merger.RORResolver", return_value=mock_ror),
        patch("merger.CountryExtractor", return_value=mock_country),
    ):
        result = merger.merge(agent_outputs, input_data)

    attrs = result["attributes"]

    # Publisher gets ROR ID
    pub = attrs["publishers"][0]
    assert pub["publisher_name"] == "Data Observatory"
    assert pub["publisher_identifier"] == "https://ror.org/05m33x406"

    # Creator gets name_identifier with ROR
    creator = attrs["creators"][0]
    assert creator["creator_name"] == "Data Observatory"
    assert len(creator["name_identifiers"]) == 1
    assert (
        creator["name_identifiers"][0]["name_identifier"] == "https://ror.org/05m33x406"
    )

    # Funder gets funder_identifier with ROR
    fref = attrs["funding_references"][0]
    assert len(fref["funder_identifiers"]) == 1
    assert (
        fref["funder_identifiers"][0]["funder_identifier"]
        == "https://ror.org/05m33x406"
    )


# ---------------------------------------------------------------------------
# Test 4 — IANA format edge cases
# ---------------------------------------------------------------------------


def test_full_pipeline_iana_format_edge_cases(merger):
    """Feed media_files with various format strings and assert correct
    normalisation or preservation.

    Cases covered:
    - "CSV"              → name_lookup → "text/csv"
    - "Application/JSON"  → lowercase → "application/json"
    - "text/csv; charset=utf-8" → strip params → "text/csv"
    - "unknown/format"    → preserved unchanged
    """
    agent_outputs = {
        "agent_a": {
            "titles": [{"name": "Format Edge Cases", "title_type": "MainTitle"}],
            "media_files": [
                {
                    "format": "CSV",
                    "file_uri": "https://example.com/data1.csv",
                    "sizes": [],
                },
                {
                    "format": "Application/JSON",
                    "file_uri": "https://example.com/data2.json",
                    "sizes": [],
                },
                {
                    "format": "text/csv; charset=utf-8",
                    "file_uri": "https://example.com/data3.csv",
                    "sizes": [],
                },
                {
                    "format": "unknown/format",
                    "file_uri": "https://example.com/data4.unk",
                    "sizes": [],
                },
            ],
        }
    }

    # No ROR calls expected — no publishers/creators → no institutions
    mock_ror = MagicMock()
    mock_country = MagicMock()
    mock_country.extract_country.return_value = None

    with (
        patch("merger.RORResolver", return_value=mock_ror),
        patch("merger.CountryExtractor", return_value=mock_country),
    ):
        result = merger.merge(agent_outputs)

    media = result["attributes"]["media_files"]
    assert len(media) == 4

    # "CSV" → name_lookup → "text/csv"
    assert media[0]["format"] == "text/csv"

    # "Application/JSON" → lowercase → "application/json"
    assert media[1]["format"] == "application/json"

    # "text/csv; charset=utf-8" → strip params → "text/csv"
    assert media[2]["format"] == "text/csv"

    # "unknown/format" → preserved unchanged (trimmed only)
    assert media[3]["format"] == "unknown/format"

    # ROR resolver should NOT have been called (no institutions to resolve)
    mock_ror.resolve_batch.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5 — Input-driven publishers + no agent publishers
# ---------------------------------------------------------------------------


def test_full_pipeline_input_driven_publisher(merger):
    """Merge where publishers come only from input_data (not agent_outputs).

    The merger's _fill_from_input creates a publisher entry from
    input_data["publisher"].  ROR enrichment should then resolve it.
    """
    agent_outputs = {
        "agent_a": {
            "titles": [{"name": "Input-driven pub", "title_type": "MainTitle"}],
            "descriptions": [
                {
                    "description": "Only input provides the publisher",
                    "description_type": "Abstract",
                }
            ],
        }
    }

    input_data = {
        "url": "https://www.hacienda.cl/dataset/fiscal",
        "publisher": "Ministerio de Hacienda",
    }

    mock_ror = _mock_ror_resolver(
        {
            "Ministerio de Hacienda": _ror_result(
                "https://ror.org/01h6h5x94", "Ministerio de Hacienda"
            ),
        }
    )
    mock_country = _mock_country_extractor("CL")

    with (
        patch("merger.RORResolver", return_value=mock_ror),
        patch("merger.CountryExtractor", return_value=mock_country),
    ):
        result = merger.merge(agent_outputs, input_data)

    attrs = result["attributes"]

    # Publisher created from input_data
    pubs = attrs["publishers"]
    assert len(pubs) == 1
    assert pubs[0]["publisher_name"] == "Ministerio de Hacienda"
    assert pubs[0]["publisher_identifier"] == "https://ror.org/01h6h5x94"

    # Creator also auto-generated from publisher name
    creators = attrs["creators"]
    assert len(creators) == 1
    assert creators[0]["creator_name"] == "Ministerio de Hacienda"
    assert len(creators[0]["name_identifiers"]) == 1
    assert (
        creators[0]["name_identifiers"][0]["name_identifier"]
        == "https://ror.org/01h6h5x94"
    )
