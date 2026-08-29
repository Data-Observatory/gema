"""Tests for scripts/curate_ror_isni.py's CSV round-trip and promotion logic.

scripts/ has no package __init__.py and isn't on pythonpath (only src/ is,
per pyproject.toml) -- insert it explicitly, same convention as other
scripts/ test modules in this repo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

_scripts = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from curate_ror_isni import (  # noqa: E402
    csv_to_review_entries,
    promote_entries,
    promote_to_overrides,
    review_to_csv,
)


def _write_review(path: Path, organizations: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"organizations": organizations}), encoding="utf-8")


def _sample_organizations() -> list[dict[str, object]]:
    return [
        {
            "org_name": "Universidad de Chile",
            "current_identifiers": [{"scheme": "VIAF", "value": "123"}],
            "seen_in_files": ["104.json", "124.json"],
            "approved_ror_id": None,
            "approved_isni_id": None,
            "country": None,
            "ror_candidate": {
                "ror_id": "https://ror.org/047gc3g35",
                "display_name": "Universidad de Chile",
            },
            "ror_alternatives": [],
            "lookup_error": None,
        },
        {
            "org_name": "Ministerio de Salud",
            "current_identifiers": [],
            "seen_in_files": ["87.json"],
            "approved_ror_id": None,
            "approved_isni_id": None,
            "country": None,
            "ror_candidate": None,
            "ror_alternatives": [
                {"ror_id": "https://ror.org/aaa", "display_name": "Alt A"},
                {"ror_id": "https://ror.org/bbb", "display_name": "Alt B"},
            ],
            "lookup_error": None,
        },
    ]


class TestReviewToCSV:
    def test_flattens_one_row_per_org(self, tmp_path: Path) -> None:
        review_path = tmp_path / "review.json"
        _write_review(review_path, _sample_organizations())
        csv_path = tmp_path / "review.csv"

        count = review_to_csv(review_path, csv_path)

        assert count == 2
        rows = csv_path.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 3  # header + 2 rows
        assert "org_name" in rows[0]
        assert "ror_candidate_id" in rows[0]

    def test_current_identifiers_and_alternatives_are_readable(self, tmp_path: Path) -> None:
        review_path = tmp_path / "review.json"
        _write_review(review_path, _sample_organizations())
        csv_path = tmp_path / "review.csv"
        review_to_csv(review_path, csv_path)

        import csv as csv_mod

        with csv_path.open(newline="", encoding="utf-8") as f:
            rows = list(csv_mod.DictReader(f))
        assert rows[0]["current_identifiers"] == "VIAF:123"
        assert rows[0]["ror_candidate_id"] == "https://ror.org/047gc3g35"
        assert rows[1]["ror_alt1_id"] == "https://ror.org/aaa"
        assert rows[1]["ror_alt2_id"] == "https://ror.org/bbb"
        assert rows[1]["ror_alt3_id"] == ""


class TestCSVRoundTrip:
    """CSV -> filled decisions -> promoted overrides.yaml must match the
    JSON-only promotion path exactly."""

    def test_csv_and_json_paths_produce_identical_overrides(self, tmp_path: Path) -> None:
        organizations = _sample_organizations()
        organizations[0]["approved_ror_id"] = "https://ror.org/047gc3g35"
        organizations[1]["approved_ror_id"] = "https://ror.org/05mvn5w28"
        organizations[1]["country"] = "CL"

        review_path = tmp_path / "review.json"
        _write_review(review_path, organizations)

        json_overrides = tmp_path / "overrides_via_json.yaml"
        json_count = promote_to_overrides(review_path, json_overrides)

        csv_path = tmp_path / "review.csv"
        review_to_csv(review_path, csv_path)
        csv_overrides = tmp_path / "overrides_via_csv.yaml"
        csv_count = promote_entries(csv_to_review_entries(csv_path), csv_overrides)

        assert json_count == csv_count == 2
        json_data = yaml.safe_load(json_overrides.read_text(encoding="utf-8"))
        csv_data = yaml.safe_load(csv_overrides.read_text(encoding="utf-8"))
        assert json_data == csv_data

    def test_unfilled_rows_are_not_promoted(self, tmp_path: Path) -> None:
        review_path = tmp_path / "review.json"
        _write_review(review_path, _sample_organizations())  # no decisions filled in
        csv_path = tmp_path / "review.csv"
        review_to_csv(review_path, csv_path)

        overrides_path = tmp_path / "overrides.yaml"
        count = promote_entries(csv_to_review_entries(csv_path), overrides_path)

        assert count == 0
        data = yaml.safe_load(overrides_path.read_text(encoding="utf-8"))
        assert data == {"overrides": []}

    def test_promote_from_csv_is_idempotent_by_name_and_country(self, tmp_path: Path) -> None:
        organizations = _sample_organizations()
        organizations[0]["approved_ror_id"] = "https://ror.org/047gc3g35"
        review_path = tmp_path / "review.json"
        _write_review(review_path, organizations)
        csv_path = tmp_path / "review.csv"
        review_to_csv(review_path, csv_path)

        overrides_path = tmp_path / "overrides.yaml"
        promote_entries(csv_to_review_entries(csv_path), overrides_path)
        promote_entries(csv_to_review_entries(csv_path), overrides_path)  # re-run

        data = yaml.safe_load(overrides_path.read_text(encoding="utf-8"))
        assert len(data["overrides"]) == 1

    def test_duplicate_name_country_rows_promote_once_not_twice(self, tmp_path: Path) -> None:
        """Two input rows deduping to the same (name, country) key must
        count as one promotion, matching what actually lands in the YAML --
        not the number of input rows processed."""
        organizations = _sample_organizations()
        organizations[0]["approved_ror_id"] = "https://ror.org/047gc3g35"
        dup = dict(organizations[0])
        entries = [organizations[0], dup]

        overrides_path = tmp_path / "overrides.yaml"
        count = promote_entries(entries, overrides_path)

        assert count == 1
        data = yaml.safe_load(overrides_path.read_text(encoding="utf-8"))
        assert len(data["overrides"]) == 1


class TestInvalidApprovedIdentifiersAreSkipped:
    """A malformed approved_ror_id/approved_isni_id must never reach
    overrides.yaml -- IdentifierResolver trusts an override at
    confidence=1.0 with no further check, so garbage here would silently
    poison every future match for that organization."""

    def test_display_name_pasted_into_ror_column_is_rejected(self, tmp_path: Path) -> None:
        entries = [
            {
                "org_name": "Universidad de Chile",
                "approved_ror_id": "University of Chile",  # a name, not an id
                "approved_isni_id": None,
                "country": None,
            }
        ]
        overrides_path = tmp_path / "overrides.yaml"
        count = promote_entries(entries, overrides_path)

        assert count == 0
        data = yaml.safe_load(overrides_path.read_text(encoding="utf-8"))
        assert data == {"overrides": []}

    def test_malformed_isni_is_rejected(self, tmp_path: Path) -> None:
        entries = [
            {
                "org_name": "Ministerio de Salud",
                "approved_ror_id": None,
                "approved_isni_id": "not-an-isni",
                "country": None,
            }
        ]
        overrides_path = tmp_path / "overrides.yaml"
        count = promote_entries(entries, overrides_path)

        assert count == 0
        data = yaml.safe_load(overrides_path.read_text(encoding="utf-8"))
        assert data == {"overrides": []}

    def test_valid_id_alongside_invalid_one_still_promotes(self, tmp_path: Path) -> None:
        entries = [
            {
                "org_name": "Universidad de Chile",
                "approved_ror_id": "https://ror.org/047gc3g35",
                "approved_isni_id": None,
                "country": None,
            },
            {
                "org_name": "Bogus Org",
                "approved_ror_id": "not-a-ror-id",
                "approved_isni_id": None,
                "country": None,
            },
        ]
        overrides_path = tmp_path / "overrides.yaml"
        count = promote_entries(entries, overrides_path)

        assert count == 1
        data = yaml.safe_load(overrides_path.read_text(encoding="utf-8"))
        assert len(data["overrides"]) == 1
        assert data["overrides"][0]["name"] == "Universidad de Chile"


class TestCSVBOMHandling:
    """Excel's default 'CSV UTF-8' save/open both use a byte-order mark --
    without utf-8-sig on both sides, the BOM folds into the first header
    name, org_name lookups silently return "", and promotion reports success
    while writing empty names."""

    def test_written_csv_carries_a_bom_and_still_reads_org_name(self, tmp_path: Path) -> None:
        review_path = tmp_path / "review.json"
        _write_review(review_path, _sample_organizations())
        csv_path = tmp_path / "review.csv"
        review_to_csv(review_path, csv_path)

        # utf-8-sig writes the BOM Excel's "CSV UTF-8" export expects.
        assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")

        entries = csv_to_review_entries(csv_path)
        assert entries[0]["org_name"] == "Universidad de Chile"

    def test_bom_prefixed_external_csv_still_reads_org_name(self, tmp_path: Path) -> None:
        """A CSV someone else produced (not via review_to_csv) with a BOM
        must round-trip too -- utf-8-sig strips a BOM on read regardless of
        who wrote it."""
        bommed = tmp_path / "external.csv"
        bommed.write_bytes(
            "﻿"
            "org_name,approved_ror_id,approved_isni_id,country\r\n"
            "Universidad de Chile,https://ror.org/047gc3g35,,\r\n".encode("utf-8")
        )

        entries = csv_to_review_entries(bommed)
        assert entries[0]["org_name"] == "Universidad de Chile"
        assert entries[0]["approved_ror_id"] == "https://ror.org/047gc3g35"

    def test_written_csv_round_trips_accented_names(self, tmp_path: Path) -> None:
        organizations = [
            {
                "org_name": "Universidad de Concepción",
                "current_identifiers": [],
                "seen_in_files": ["x.json"],
                "approved_ror_id": None,
                "approved_isni_id": None,
                "country": None,
                "ror_candidate": None,
                "ror_alternatives": [],
                "lookup_error": None,
            }
        ]
        review_path = tmp_path / "review.json"
        _write_review(review_path, organizations)
        csv_path = tmp_path / "review.csv"
        review_to_csv(review_path, csv_path)

        entries = csv_to_review_entries(csv_path)
        assert entries[0]["org_name"] == "Universidad de Concepción"
