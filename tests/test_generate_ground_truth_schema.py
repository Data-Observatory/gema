"""Tests for scripts/generate_ground_truth_schema.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_scripts = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from generate_ground_truth_schema import OUTPUT_PATH  # noqa: E402


class TestGeneratedSchema:
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
