"""Integration tests for IANA media type normalization and ROR enrichment."""

from unittest.mock import patch, MagicMock

import pytest

from merger import MetadataMerger


@pytest.fixture
def merger():
    return MetadataMerger()


def _make_agent_output(media_files):
    return {
        "agent_a": {
            "titles": [{"name": "Test Dataset", "title_type": "MainTitle"}],
            "media_files": media_files,
        }
    }


def test_iana_normalizes_messy_format(merger):
    result = merger.merge(
        _make_agent_output(
            [{"format": " Application/PDF ", "file_uri": "https://example.com/doc.pdf"}]
        )
    )
    formats = [f["format"] for f in result["attributes"]["media_files"]]
    assert formats == ["application/pdf"]


def test_iana_valid_mime_unchanged(merger):
    result = merger.merge(
        _make_agent_output(
            [{"format": "text/csv", "file_uri": "https://example.com/data.csv"}]
        )
    )
    formats = [f["format"] for f in result["attributes"]["media_files"]]
    assert formats == ["text/csv"]


def test_iana_unknown_format_preserved(merger):
    result = merger.merge(
        _make_agent_output(
            [{"format": "x-custom/binary", "file_uri": "https://example.com/data.bin"}]
        )
    )
    formats = [f["format"] for f in result["attributes"]["media_files"]]
    assert formats == ["x-custom/binary"]


def test_iana_empty_format_unchanged(merger):
    result = merger.merge(
        _make_agent_output([{"format": "", "file_uri": "https://example.com/data"}])
    )
    assert result["attributes"]["media_files"][0].get("format", "") == ""


def test_iana_no_media_files_no_error(merger):
    result = merger.merge(
        {"agent_a": {"titles": [{"name": "Test", "title_type": "MainTitle"}]}}
    )
    assert "media_files" not in result["attributes"]


# ---------------------------------------------------------------------------
# ROR enrichment integration tests
# ---------------------------------------------------------------------------


def _ror_result(ror_id, name, country_code="CL"):
    return {"id": ror_id, "name": name, "country_code": country_code}


def _make_ror_agent_outputs(publisher_name="Ministerio de Hacienda"):
    return {
        "agent_a": {
            "titles": [{"name": "Test Dataset", "title_type": "MainTitle"}],
            "publishers": [{"publisher_name": publisher_name}],
            "creators": [
                {
                    "creator_name": publisher_name,
                    "creator_name_type": "Organizational",
                    "type": "Organization",
                    "name_identifiers": [],
                    "affiliations": [],
                }
            ],
        }
    }


def test_ror_publisher_name_resolved_to_id(merger):
    mock_resolver = MagicMock()
    mock_resolver.resolve_batch.return_value = {
        "Ministerio de Hacienda": _ror_result(
            "https://ror.org/01h6h5x94", "Ministerio de Hacienda"
        )
    }
    mock_country = MagicMock()
    mock_country.extract_country.return_value = "CL"

    with (
        patch("merger.RORResolver", return_value=mock_resolver),
        patch("merger.CountryExtractor", return_value=mock_country),
    ):
        result = merger.merge(
            _make_ror_agent_outputs(),
            input_data={"url": "https://datos.gob.cl/dataset/test"},
        )

    pub = result["attributes"]["publishers"][0]
    assert pub["publisher_identifier"] == "https://ror.org/01h6h5x94"
    assert pub["publisher_identifier_scheme"] == "ROR"
    assert pub["publisher_scheme_uri"] == "https://ror.org"


def test_ror_existing_identifier_preserved(merger):
    mock_resolver = MagicMock()
    mock_country = MagicMock()
    mock_country.extract_country.return_value = "CL"
    agent_outputs = {
        "agent_a": {
            "titles": [{"name": "Test", "title_type": "MainTitle"}],
            "publishers": [
                {
                    "publisher_name": "Already Has ROR",
                    "publisher_identifier": "https://ror.org/0existing",
                    "publisher_identifier_scheme": "ROR",
                    "publisher_scheme_uri": "https://ror.org",
                }
            ],
        }
    }

    with (
        patch("merger.RORResolver", return_value=mock_resolver),
        patch("merger.CountryExtractor", return_value=mock_country),
    ):
        result = merger.merge(
            agent_outputs,
            input_data={"url": "https://datos.gob.cl/dataset/test"},
        )

    mock_resolver.resolve_batch.assert_not_called()
    pub = result["attributes"]["publishers"][0]
    assert pub["publisher_identifier"] == "https://ror.org/0existing"


def test_ror_no_institutions_no_api_calls(merger):
    mock_resolver = MagicMock()
    agent_outputs = {
        "agent_a": {
            "titles": [{"name": "Test", "title_type": "MainTitle"}],
            "descriptions": [
                {"description": "Just a description", "description_type": "Abstract"}
            ],
        }
    }

    with patch("merger.RORResolver", return_value=mock_resolver):
        result = merger.merge(
            agent_outputs,
            input_data={"url": "https://example.com"},
        )

    mock_resolver.resolve_batch.assert_not_called()
    assert "publishers" not in result["attributes"]


def test_ror_api_returns_none_pipeline_completes(merger):
    mock_resolver = MagicMock()
    mock_resolver.resolve_batch.return_value = {"Unknown Org": None}
    mock_country = MagicMock()
    mock_country.extract_country.return_value = "CL"

    with (
        patch("merger.RORResolver", return_value=mock_resolver),
        patch("merger.CountryExtractor", return_value=mock_country),
    ):
        result = merger.merge(
            _make_ror_agent_outputs("Unknown Org"),
            input_data={"url": "https://datos.gob.cl/dataset/test"},
        )

    pub = result["attributes"]["publishers"][0]
    assert "publisher_identifier" not in pub


def test_ror_creator_name_identifier_injected(merger):
    mock_resolver = MagicMock()
    mock_resolver.resolve_batch.return_value = {
        "Universidad de Chile": _ror_result(
            "https://ror.org/01q2pz218", "Universidad de Chile"
        )
    }
    mock_country = MagicMock()
    mock_country.extract_country.return_value = "CL"
    agent_outputs = {
        "agent_a": {
            "titles": [{"name": "Test", "title_type": "MainTitle"}],
            "creators": [
                {
                    "creator_name": "Universidad de Chile",
                    "creator_name_type": "Organizational",
                    "type": "Organization",
                    "name_identifiers": [],
                    "affiliations": [],
                }
            ],
        }
    }

    with (
        patch("merger.RORResolver", return_value=mock_resolver),
        patch("merger.CountryExtractor", return_value=mock_country),
    ):
        result = merger.merge(
            agent_outputs,
            input_data={"url": "https://datos.uchile.cl/dataset/test"},
        )

    creator = result["attributes"]["creators"][0]
    name_ids = creator["name_identifiers"]
    assert len(name_ids) == 1
    assert name_ids[0]["name_identifier"] == "https://ror.org/01q2pz218"
    assert name_ids[0]["name_identifier_scheme"] == "ROR"
    assert name_ids[0]["scheme_uri"] == "https://ror.org"


def test_ror_funding_reference_injected(merger):
    mock_resolver = MagicMock()
    mock_resolver.resolve_batch.return_value = {
        "ANID": _ror_result("https://ror.org/02q2pz218", "ANID")
    }
    mock_country = MagicMock()
    mock_country.extract_country.return_value = "CL"
    agent_outputs = {
        "agent_a": {
            "titles": [{"name": "Test", "title_type": "MainTitle"}],
            "funding_references": [
                {
                    "funder_name": "ANID",
                    "funding_stream": "Fondecyt",
                    "award_number": "123456",
                    "award_uri": "",
                    "award_title": "Test project",
                    "funder_identifiers": [],
                }
            ],
        }
    }

    with (
        patch("merger.RORResolver", return_value=mock_resolver),
        patch("merger.CountryExtractor", return_value=mock_country),
    ):
        result = merger.merge(
            agent_outputs,
            input_data={"url": "https://anid.cl"},
        )

    fref = result["attributes"]["funding_references"][0]
    assert len(fref["funder_identifiers"]) == 1
    assert (
        fref["funder_identifiers"][0]["funder_identifier"]
        == "https://ror.org/02q2pz218"
    )
    assert fref["funder_identifiers"][0]["funder_identifier_type"] == "ROR"
