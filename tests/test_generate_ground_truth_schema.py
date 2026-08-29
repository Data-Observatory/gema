"""Tests for scripts/generate_ground_truth_schema.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_scripts = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from generate_ground_truth_schema import OUTPUT_PATH  # noqa: E402
from metadata_enricher.schemas.datacite import DataCiteOutputModel  # noqa: E402


class TestGeneratedSchema:
    def test_committed_schema_matches_the_live_model(self) -> None:
        """Nothing previously checked the committed file stays in sync with
        DataCiteOutputModel -- a schema field change would silently leave
        the student's editor validating against a stale schema forever.
        This is the drift alarm: a model change that isn't followed by
        re-running scripts/generate_ground_truth_schema.py now fails
        `make test`, the same discipline golden-fixture regression already
        follows for prompt/model changes."""
        committed = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        assert committed == DataCiteOutputModel.model_json_schema()

    def test_schema_file_is_committed_and_valid_json(self) -> None:
        assert OUTPUT_PATH.is_file(), "run scripts/generate_ground_truth_schema.py"
        schema = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is True
        assert "titles" in schema["properties"]
        assert "creators" in schema["properties"]

    def test_a_real_ground_truth_file_has_only_allowed_extra_keys(self) -> None:
        """additionalProperties: true means do_catalog's roles/origin_name
        keys (absent from DataCiteOutputModel) never break validation --
        this just documents that expectation with a real fixture."""
        schema = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        gt_path = Path(__file__).parent / "fixtures/do_catalog/ground_truth/104.json"
        data = json.loads(gt_path.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is True
        assert "roles" not in schema["properties"]
        assert "roles" in data  # confirms the shape mismatch this test guards
