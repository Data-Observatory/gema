"""Tests for scripts/eval_common.py's scoring helpers.

scripts/ has no package __init__.py and isn't on pythonpath (only src/ is,
per pyproject.toml) -- other scripts rely on being executed with scripts/
itself as cwd/sys.path[0]. Insert it explicitly here instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_scripts = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from eval_common import extract_rights_id, strip_ignored_fields  # noqa: E402


class TestExtractRightsId:
    """extract_rights_id: first non-empty rights_identifier in rights[]."""

    def test_empty_rights_list(self) -> None:
        assert extract_rights_id({"rights": []}) == ""

    def test_missing_rights_key(self) -> None:
        assert extract_rights_id({}) == ""

    def test_single_entry_with_identifier(self) -> None:
        attrs = {"rights": [{"rights_identifier": "CC-BY-4.0"}]}
        assert extract_rights_id(attrs) == "cc-by-4.0"

    def test_first_entry_empty_second_entry_has_identifier(self) -> None:
        """The bug this guards: previously only rights[0] was ever read, so
        a real identifier sitting in a later entry was silently missed."""
        attrs = {
            "rights": [
                {"rights_identifier": ""},
                {"rights_identifier": "ODbL-1.0"},
            ]
        }
        assert extract_rights_id(attrs) == "odbl-1.0"

    def test_first_entry_has_identifier_second_does_not(self) -> None:
        attrs = {
            "rights": [
                {"rights_identifier": "CC-BY-SA-4.0"},
                {"rights_identifier": ""},
            ]
        }
        assert extract_rights_id(attrs) == "cc-by-sa-4.0"

    def test_no_entry_has_an_identifier(self) -> None:
        attrs = {"rights": [{"rights_identifier": ""}, {}]}
        assert extract_rights_id(attrs) == ""

    def test_rights_not_a_list(self) -> None:
        assert extract_rights_id({"rights": "not-a-list"}) == ""


class TestStripIgnoredFields:
    """strip_ignored_fields: schema:dateModified must never affect a judge
    score -- it's a processing-time injection (today's date), not something
    any agent extracts, so comparing it just measures the wall-clock gap
    between recording and running (Finding B-1,
    docs/cdif_pivot_implementation_plan.md's Post-PR#45 investigation)."""

    def test_removes_date_modified(self) -> None:
        doc = {"schema:name": "X", "schema:dateModified": "2026-09-04"}
        result = json.loads(strip_ignored_fields(json.dumps(doc)))
        assert "schema:dateModified" not in result
        assert result["schema:name"] == "X"

    def test_missing_date_modified_is_a_noop(self) -> None:
        doc = {"schema:name": "X"}
        result = json.loads(strip_ignored_fields(json.dumps(doc)))
        assert result == doc

    def test_malformed_json_returned_unchanged(self) -> None:
        assert strip_ignored_fields("not json") == "not json"

    def test_non_dict_json_returned_unchanged(self) -> None:
        assert json.loads(strip_ignored_fields(json.dumps([1, 2, 3]))) == [1, 2, 3]
