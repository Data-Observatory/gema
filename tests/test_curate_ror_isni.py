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
            "ror_candidate": {"ror_id": "https://ror.org/047gc3g35", "display_name": "Universidad de Chile"},
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
        organizations[1]["approved_ror_id"] = "https://ror.org/aaa"
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
