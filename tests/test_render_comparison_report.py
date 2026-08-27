"""Tests for scripts/render_comparison_report.py.

scripts/ has no package __init__.py and isn't on pythonpath (only src/ is,
per pyproject.toml) -- insert it explicitly, same convention as other
scripts/ test modules in this repo.
"""

from __future__ import annotations

import json
import sys
from html.parser import HTMLParser
from pathlib import Path

_scripts = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from render_comparison_report import build_rows, render_html  # noqa: E402


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _setup_fixture(tmp_path: Path) -> tuple[Path, Path]:
    gt_dir = tmp_path / "ground_truth"
    output_root = tmp_path / "run"

    _write_json(
        gt_dir / "104.json",
        {
            "roles": [
                {
                    "type": "Creator",
                    "role_name_type": "Organizational",
                    "role_name": "Instituto Nacional de Estadísticas (Chile)",
                    "name_identifiers": [],
                    "affiliations": [],
                }
            ],
            "publishers": [],
            "subjects": [{"subject": "household surveys - chile"}],
            "categories": [{"name": "Ciencias Sociales", "sub_category": "Economía"}],
            "rights": [{"rights_identifier": "CC-BY-SA-4.0"}],
            "languages": [{"lang_code": "es-cl"}],
            "geo_locations": [{"geo_location_place": "Chile"}],
            "media_files": [{"format": "text/csv"}],
        },
    )
    _write_json(
        output_root / "outputs" / "some-model" / "104.json",
        {
            "creators": [{"creator_name": "Instituto Nacional de Estadísticas (Chile)", "name_identifiers": []}],
            "publishers": [],
            "subjects": [{"subject": "encuestas de hogares"}],
            "categories": [{"name": "Ciencias Sociales", "sub_category": "Economía"}],
            "rights": [],
            "languages": [{"lang_code": "es"}],
            "geo_locations": [{"geo_location_place": "Chile"}],
            "media_files": [{"format": "text/csv"}],
        },
    )
    comparison_data = {
        "models": {
            "some-model": {
                "avg_overall": 0.6,
                "results": [
                    {
                        "input": "104.json",
                        "scores": {
                            "overall": 0.6,
                            "creators_name": 1.0,
                            "ror_match": 1.0,
                            "subjects": 0.0,
                            "categories": 1.0,
                            "rights": 0.0,
                            "languages": 0.0,
                            "field_coverage": 0.8,
                            "geo_places": 1.0,
                            "media_formats": 1.0,
                            "orcid_match": 1.0,
                        },
                    }
                ],
            }
        }
    }
    _write_json(output_root / "comparison_data.json", comparison_data)
    return gt_dir, output_root


class TestBuildRows:
    def test_one_item_with_all_metrics(self, tmp_path: Path) -> None:
        gt_dir, output_root = _setup_fixture(tmp_path)
        data = json.loads((output_root / "comparison_data.json").read_text(encoding="utf-8"))
        results = data["models"]["some-model"]["results"]

        items = build_rows(output_root, gt_dir, "some-model", results)

        assert len(items) == 1
        assert items[0]["input"] == "104.json"
        metrics = {m["metric"]: m for m in items[0]["metrics"]}
        # eval_common's extractors lowercase-normalize for comparison --
        # reused as-is here, so the report shows exactly what's scored.
        assert metrics["languages"]["truth"] == "es-cl"
        assert metrics["languages"]["actual"] == "es"
        assert metrics["languages"]["score"] == 0.0
        assert metrics["rights"]["truth"] == "cc-by-sa-4.0"
        assert metrics["rights"]["actual"] == "(empty)"
        assert metrics["creators_name"]["truth"] == "instituto nacional de estadisticas (chile)"

    def test_missing_actual_output_does_not_crash(self, tmp_path: Path) -> None:
        gt_dir, output_root = _setup_fixture(tmp_path)
        results = [{"input": "missing.json", "scores": {"overall": 0.0, "creators_name": 0.0}}]

        items = build_rows(output_root, gt_dir, "some-model", results)

        assert len(items) == 1
        metrics = {m["metric"]: m for m in items[0]["metrics"]}
        assert metrics["creators_name"]["truth"] == "(empty)"
        assert metrics["creators_name"]["actual"] == "(empty)"

    def test_items_sorted_worst_overall_first(self, tmp_path: Path) -> None:
        gt_dir, output_root = _setup_fixture(tmp_path)
        results = [
            {"input": "104.json", "scores": {"overall": 0.9}},
            {"input": "missing.json", "scores": {"overall": 0.1}},
        ]
        items = build_rows(output_root, gt_dir, "some-model", results)
        assert [it["input"] for it in items] == ["missing.json", "104.json"]


class TestRenderHTML:
    def test_produces_parseable_html_with_expected_content(self, tmp_path: Path) -> None:
        gt_dir, output_root = _setup_fixture(tmp_path)
        comparison_data = json.loads((output_root / "comparison_data.json").read_text(encoding="utf-8"))

        html = render_html(comparison_data, output_root, gt_dir)

        class _Checker(HTMLParser):
            pass

        _Checker().feed(html)  # raises on structurally broken markup
        assert "some-model" in html
        assert "es-cl" in html
        assert "cc-by-sa-4.0" in html

    def test_no_models_renders_placeholder(self, tmp_path: Path) -> None:
        html = render_html({"models": {}}, tmp_path, tmp_path)
        assert "No results" in html
