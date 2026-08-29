"""Tests for scripts/validate_ground_truth.py.

scripts/ has no package __init__.py and isn't on pythonpath (only src/ is,
per pyproject.toml) -- insert it explicitly, same convention as
tests/test_eval_common.py and tests/test_do_catalog_common.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_scripts = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from validate_ground_truth import REQUIRED_KEYS, validate_dir, validate_record  # noqa: E402


def _base_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {key: [] for key in REQUIRED_KEYS}
    record["resource"] = {}
    record["origin_name"] = "Data Observatory"
    record["origin_priority"] = 1
    record.update(overrides)
    return record


class TestRequiredKeys:
    def test_complete_record_has_no_missing_key_violation(self) -> None:
        violations = validate_record("ok", _base_record())
        assert not any("missing required keys" in v.message for v in violations)

    def test_missing_key_is_reported(self) -> None:
        record = _base_record()
        del record["titles"]
        violations = validate_record("bad", record)
        assert any("titles" in v.message for v in violations)
        assert any(not v.warning for v in violations)


class TestSwappedFieldDetection:
    """The exact corruption class found in 104.json/124.json/87.json."""

    def test_org_name_in_name_identifier_is_rejected(self) -> None:
        record = _base_record(
            roles=[
                {
                    "name_identifiers": [
                        {
                            "name_identifier": "Instituto Nacional de Estadísticas (Chile)",
                            "name_identifier_scheme": "ISNI",
                            "scheme_uri": "https://isni.org/isni/0000000122977777",
                        }
                    ],
                    "affiliations": [],
                }
            ]
        )
        violations = validate_record("swapped", record)
        failures = [v for v in violations if not v.warning]
        assert len(failures) == 2  # bad value shape + embedded id in scheme_uri
        assert any("swapped-field corruption" in v.message for v in failures)
        assert any("embedded identifier-like digit run" in v.message for v in failures)

    def test_repaired_shape_is_clean(self) -> None:
        record = _base_record(
            roles=[
                {
                    "name_identifiers": [
                        {
                            "name_identifier": "0000000122977777",
                            "name_identifier_scheme": "ISNI",
                            "scheme_uri": "https://isni.org",
                        }
                    ],
                    "affiliations": [],
                }
            ]
        )
        violations = validate_record("repaired", record)
        assert not [v for v in violations if not v.warning]

    def test_uri_wrapped_isni_is_also_accepted(self) -> None:
        """Ground truth is allowed to use either bare or URI-wrapped form --
        only free text standing in for the value is rejected."""
        record = _base_record(
            roles=[
                {
                    "name_identifiers": [
                        {
                            "name_identifier": "https://isni.org/isni/0000000122977777",
                            "name_identifier_scheme": "ISNI",
                            "scheme_uri": "https://isni.org",
                        }
                    ],
                    "affiliations": [],
                }
            ]
        )
        violations = validate_record("uri-form", record)
        assert not [v for v in violations if not v.warning]

    def test_ror_publisher_identifier_shape(self) -> None:
        record = _base_record(
            publishers=[{"publisher_identifier": "not-a-ror", "publisher_identifier_scheme": "ROR"}]
        )
        violations = validate_record("bad-ror", record)
        assert any("ROR" in v.message and not v.warning for v in violations)

    def test_bare_ror_id_is_accepted(self) -> None:
        """IdentifierEnricher itself can emit a bare (non-URI-wrapped) ROR
        id -- the validator must not be stricter than the pipeline."""
        record = _base_record(
            publishers=[{"publisher_identifier": "047gc3g35", "publisher_identifier_scheme": "ROR"}]
        )
        violations = validate_record("bare-ror", record)
        assert not [v for v in violations if not v.warning]

    def test_ror_with_garbage_after_prefix_is_rejected(self) -> None:
        """A real ROR id is always exactly 9 characters -- anything else
        after the ror.org/ prefix must fail, not silently pass."""
        record = _base_record(
            publishers=[
                {
                    "publisher_identifier": "https://ror.org/NOTAROR",
                    "publisher_identifier_scheme": "ROR",
                }
            ]
        )
        violations = validate_record("garbage-ror", record)
        assert any("ROR" in v.message and not v.warning for v in violations)

    def test_isni_spaced_form_is_accepted(self) -> None:
        """do_catalog_common.py's scorer already treats the space-grouped
        ISNI display form as equivalent to the compact form -- the validator
        must not be stricter than what actually gets scored."""
        record = _base_record(
            publishers=[
                {
                    "publisher_identifier": "0000 0001 2223 8173",
                    "publisher_identifier_scheme": "ISNI",
                }
            ]
        )
        violations = validate_record("spaced-isni", record)
        assert not [v for v in violations if not v.warning]

    def test_isni_bad_checksum_is_rejected(self) -> None:
        """Right shape, wrong check digit -- the likeliest residual error
        after a manual repair (a single mistyped digit)."""
        record = _base_record(
            publishers=[
                {"publisher_identifier": "0000000122238174", "publisher_identifier_scheme": "ISNI"}
            ]
        )
        violations = validate_record("bad-checksum", record)
        failures = [v for v in violations if not v.warning]
        assert any("check digit" in v.message for v in failures)

    def test_viaf_scheme_uri_corruption_is_still_caught(self) -> None:
        """VIAF has no value-shape pattern to check against, but the
        embedded-identifier scheme_uri check must still run for it -- the
        same swapped-field corruption is possible for any scheme."""
        record = _base_record(
            publishers=[
                {
                    "publisher_identifier": "154434202",
                    "publisher_identifier_scheme": "VIAF",
                    "publisher_scheme_uri": "https://viaf.org/viaf/154434202",
                }
            ]
        )
        violations = validate_record("viaf-corrupted", record)
        failures = [v for v in violations if not v.warning]
        assert any("embedded identifier-like digit run" in v.message for v in failures)


class TestSPDXCasingWarning:
    def test_lowercase_cc_is_a_warning_not_a_failure(self) -> None:
        record = _base_record(rights=[{"rights_identifier": "cc-by-4.0"}])
        violations = validate_record("cc-case", record)
        assert violations and all(v.warning for v in violations)

    def test_gfdl_mixed_case_is_not_flagged(self) -> None:
        """GFDL/ODbL are legitimately mixed-case in the real SPDX license
        list -- must not be false-flagged like a Creative Commons id."""
        record = _base_record(rights=[{"rights_identifier": "GFDL-1.3-or-later"}])
        violations = validate_record("gfdl", record)
        assert violations == []


class TestValidateDir:
    def test_validates_every_json_file_in_directory(self, tmp_path: Path) -> None:
        import json

        good = tmp_path / "good.json"
        good.write_text(json.dumps(_base_record()), encoding="utf-8")
        bad = tmp_path / "bad.json"
        record = _base_record()
        del record["titles"]
        bad.write_text(json.dumps(record), encoding="utf-8")

        violations, count = validate_dir(tmp_path)
        assert count == 2
        assert any("bad" in v.path for v in violations)
        assert not any("good" in v.path for v in violations)

    def test_malformed_json_is_reported_not_raised(self, tmp_path: Path) -> None:
        """A trailing comma or unclosed brace must produce a [FAIL] line, not
        a traceback -- the exact defect Part A's third fix repaired in
        metadata_template.json."""
        broken = tmp_path / "broken.json"
        broken.write_text('{"titles": [],}', encoding="utf-8")

        violations, count = validate_dir(tmp_path)
        assert count == 1
        assert len(violations) == 1
        assert not violations[0].warning
        assert "invalid JSON" in violations[0].message

    def test_non_dict_top_level_is_reported_not_raised(self, tmp_path: Path) -> None:
        import json

        not_a_record = tmp_path / "list.json"
        not_a_record.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        violations, count = validate_dir(tmp_path)
        assert count == 1
        assert len(violations) == 1
        assert not violations[0].warning
        assert "must be an object" in violations[0].message


if __name__ == "__main__":
    pytest.main([__file__])
