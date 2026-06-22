"""Test fixtures for metadata enrichment modules."""

import sys
from pathlib import Path

# Ensure src/ takes priority over flat-layout metadata_enricher.py at repo root
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src in sys.path:
    sys.path.remove(_src)
sys.path.insert(0, _src)

# Pre-import to cache correct module (avoid flat-layout shadowing)

import pytest


@pytest.fixture
def mock_ror_api_response():
    """Return a sample ROR API v2 JSON response with Chilean institutions."""
    return {
        "number_of_results": 1,
        "time_taken": 1,
        "items": [
            {
                "id": "https://ror.org/01h6h5x94",
                "name": "Ministerio de Hacienda",
                "types": ["Government"],
                "status": "active",
                "established": 1817,
                "country": {
                    "country_name": "Chile",
                    "country_code": "CL",
                },
                "locations": [
                    {
                        "geonames_id": 3871336,
                        "country_geonames_id": 3895114,
                        "country": "Chile",
                        "country_code": "CL",
                        "lat": -33.4489,
                        "lng": -70.6693,
                        "state": "Region Metropolitana",
                        "state_code": "CL-RM",
                        "city": "Santiago",
                        "primary": True,
                    }
                ],
                "links": ["https://www.hacienda.cl"],
                "aliases": ["Ministry of Finance"],
                "acronyms": [],
                "wikipedia_url": "https://en.wikipedia.org/wiki/Ministry_of_Finance_(Chile)",
                "labels": [
                    {"label": "Ministerio de Hacienda", "iso639": "es"},
                    {"label": "Ministry of Finance", "iso639": "en"},
                ],
            }
        ],
        "meta": {
            "types": ["Government"],
        },
    }


@pytest.fixture
def mock_iana_data():
    """Return a sample IANA media types dict with metadata, types, and name_lookup."""
    return {
        "_metadata": {
            "last_updated": "2026-05-14T00:00:00Z",
            "source": "IANA",
            "count": 8,
        },
        "types": {
            "application/json": {
                "name": "json",
                "template": "application/json",
                "reference": "RFC 7159",
            },
            "text/csv": {
                "name": "csv",
                "template": "text/csv",
                "reference": "RFC 4180",
            },
            "application/pdf": {
                "name": "pdf",
                "template": "application/pdf",
                "reference": "RFC 3778",
            },
            "text/html": {
                "name": "html",
                "template": "text/html",
                "reference": "RFC 2854",
            },
            "application/geo+json": {
                "name": "geo+json",
                "template": "application/geo+json",
                "reference": "RFC 7946",
            },
            "application/xml": {
                "name": "xml",
                "template": "application/xml",
                "reference": "RFC 3023",
            },
            "application/zip": {
                "name": "zip",
                "template": "application/zip",
                "reference": "RFC 6713",
            },
            "text/plain": {
                "name": "plain",
                "template": "text/plain",
                "reference": "RFC 2046",
            },
        },
        "name_lookup": {
            "json": "application/json",
            "csv": "text/csv",
            "pdf": "application/pdf",
            "html": "text/html",
            "xml": "application/xml",
            "zip": "application/zip",
            "plain": "text/plain",
        },
    }


@pytest.fixture
def sample_merged_output():
    """Return a dict matching the merger output structure with realistic Chilean data."""
    return {
        "creators": [
            {
                "creator_name": "Ministerio de Hacienda",
                "creator_name_type": "Organizational",
                "given_name": "",
                "family_name": "",
                "type": "Organization",
                "name_identifiers": [
                    {
                        "name_identifier": "https://ror.org/01h6h5x94",
                        "name_identifier_scheme": "ROR",
                        "scheme_uri": "https://ror.org",
                    }
                ],
                "affiliations": [
                    {
                        "affiliation": "Ministerio de Hacienda",
                        "affiliation_identifier": "https://ror.org/01h6h5x94",
                        "affiliation_identifier_scheme": "ROR",
                    }
                ],
            },
            {
                "creator_name": "Universidad de Chile",
                "creator_name_type": "Organizational",
                "given_name": "",
                "family_name": "",
                "type": "Organization",
                "name_identifiers": [
                    {
                        "name_identifier": "https://ror.org/01q2pz218",
                        "name_identifier_scheme": "ROR",
                        "scheme_uri": "https://ror.org",
                    }
                ],
                "affiliations": [
                    {
                        "affiliation": "Universidad de Chile",
                        "affiliation_identifier": "https://ror.org/01q2pz218",
                        "affiliation_identifier_scheme": "ROR",
                    }
                ],
            },
        ],
        "publishers": [
            {
                "publisher_name": "Ministerio de Hacienda",
                "publisher_identifier": "https://ror.org/01h6h5x94",
                "publisher_identifier_scheme": "ROR",
                "publisher_scheme_uri": "https://ror.org",
            }
        ],
        "funding_references": [
            {
                "funder_name": "ANID",
                "funding_stream": "Fondecyt",
                "award_number": "123456",
                "award_uri": "https://anid.cl/proyectos/123456",
                "award_title": "Estudio de gasto fiscal",
                "funder_identifiers": [
                    {
                        "funder_identifier": "https://ror.org/02q2pz218",
                        "funder_identifier_type": "ROR",
                        "scheme_uri": "https://ror.org",
                    }
                ],
            }
        ],
        "media_files": [
            {
                "sizes": [{"size": "250", "unit": "KB"}],
                "physical_carrier": "digital",
                "format": "text/csv",
                "variable_measured": "Gastos municipales",
                "checksum": "abc123def456",
                "data_quality": "Official data",
                "measurement_technique": "Administrative records",
                "provenance": "Gobierno de Chile",
                "file_uri": "https://datos.gob.cl/dataset/gastos-municipales.csv",
                "temporal_resolution": "P1Y",
            }
        ],
    }
