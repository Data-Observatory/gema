#!/usr/bin/env python3
"""Render a static, self-contained HTML truth-vs-output diff report from a
scripts/compare_models.py run.

compare_models.py already writes comparison_data.json (aggregate per-field
*scores* only) and a Markdown summary -- neither shows the actual truth and
output values side by side. This reads comparison_data.json plus the saved
ground truth and per-model outputs (same output_root/outputs/<label>/*.json
layout compare_models.py writes) and renders one table row per (item,
metric): truth value | actual value | score -- grouped by item, worst
overall score first, so the most useful review targets surface immediately.

No new dependency: plain stdlib html.escape/f-string templating, same
convention as content_fetcher.py's stdlib-only HTML parsing.

Usage:
    uv run python scripts/render_comparison_report.py \
        --output-root reports/do_catalog/pilot_phase3c \
        --ground-truth-dir tests/fixtures/do_catalog/ground_truth
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path
from typing import Any, Callable

import do_catalog_common
import eval_common

# metric -> extractor producing a human-readable value from an (adapted)
# attrs dict -- the exact same functions eval_common.compare_outputs()/
# do_catalog_common.compare_outputs() score against, so what's displayed is
# never a re-derivation that could drift from what was actually scored.
_METRIC_EXTRACTORS: dict[str, Callable[[dict[str, Any]], object]] = {
    "creators_name": eval_common.extract_creator_names,
    "ror_match": lambda a: do_catalog_common.extract_identifiers(a, do_catalog_common.IDENTIFIER_SCHEMES),
    "orcid_match": lambda a: do_catalog_common.extract_identifiers(a, frozenset({"ORCID"})),
    "subjects": eval_common.extract_subjects,
    "categories": eval_common.extract_categories,
    "rights": eval_common.extract_rights_id,
    "languages": eval_common.extract_languages,
    "geo_places": eval_common.extract_geo_places,
    "media_formats": eval_common.extract_media_formats,
    "field_coverage": eval_common.extract_populated_fields,
}

_METRIC_ORDER = [*eval_common.WEIGHTS.keys(), "orcid_match"]


def _format_item(item: object) -> str:
    if isinstance(item, tuple):
        return ":".join(str(part) for part in item)
    return str(item)


def _format_value(value: object) -> str:
    if isinstance(value, (set, frozenset)):
        if not value:
            return "(empty)"
        return ", ".join(sorted(_format_item(v) for v in value))
    if value in ("", None):
        return "(empty)"
    return str(value)


def _load_truth(ground_truth_dir: Path, input_name: str) -> dict[str, Any] | None:
    gt_path = ground_truth_dir / input_name
    if not gt_path.exists():
        return None
    return do_catalog_common.adapt_ground_truth(json.loads(gt_path.read_text(encoding="utf-8")))


def _load_actual(output_root: Path, label: str, input_name: str) -> dict[str, Any] | None:
    out_path = output_root / "outputs" / label / input_name
    if not out_path.exists():
        return None
    result: dict[str, Any] = json.loads(out_path.read_text(encoding="utf-8"))
    return result


def build_rows(
    output_root: Path, ground_truth_dir: Path, label: str, results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """One entry per input item: its overall score plus a list of
    (metric, truth_value, actual_value, score) rows, sorted worst-item-first."""
    items = []
    for result in results:
        scores = result.get("scores") or {}
        if not scores:
            continue
        input_name = result["input"]
        truth = _load_truth(ground_truth_dir, input_name)
        actual = _load_actual(output_root, label, input_name)
        metric_rows = []
        for metric in _METRIC_ORDER:
            extractor = _METRIC_EXTRACTORS.get(metric)
            truth_val = extractor(truth) if extractor and truth is not None else None
            actual_val = extractor(actual) if extractor and actual is not None else None
            metric_rows.append({
                "metric": metric,
                "truth": _format_value(truth_val),
                "actual": _format_value(actual_val),
                "score": scores.get(metric, 0.0),
            })
        items.append({
            "input": input_name,
            "overall": scores.get("overall", 0.0),
            "metrics": metric_rows,
        })
    items.sort(key=lambda it: it["overall"])
    return items


def render_html(comparison_data: dict[str, Any], output_root: Path, ground_truth_dir: Path) -> str:
    models = comparison_data.get("models", {})
    sections = []
    for spec, mdata in models.items():
        label = eval_common.sanitize_label(spec)
        items = build_rows(output_root, ground_truth_dir, label, mdata.get("results", []))
        rows_html = []
        for item in items:
            rows_html.append(
                f'<tr class="item-row"><td colspan="4"><strong>{escape(item["input"])}</strong> '
                f'&mdash; overall {item["overall"]:.3f}</td></tr>'
            )
            for m in item["metrics"]:
                low = m["score"] < 0.5
                cls = ' class="low"' if low else ""
                rows_html.append(
                    f"<tr{cls}><td>{escape(m['metric'])}</td>"
                    f"<td>{escape(m['truth'])}</td>"
                    f"<td>{escape(m['actual'])}</td>"
                    f"<td>{m['score']:.3f}</td></tr>"
                )
        sections.append(f"""
<h2>{escape(spec)} <small>(avg overall {mdata.get('avg_overall', 0):.3f})</small></h2>
<table>
<thead><tr><th>Metric</th><th>Truth</th><th>Actual</th><th>Score</th></tr></thead>
<tbody>
{"".join(rows_html)}
</tbody>
</table>
""")

    body = "\n".join(sections) if sections else "<p>No results in comparison_data.json.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Truth vs. Output Comparison</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #222; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; table-layout: fixed; }}
  th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top;
            word-wrap: break-word; font-size: 0.9rem; }}
  th {{ background: #f0f0f0; }}
  tr.item-row td {{ background: #e8eef7; font-size: 1rem; }}
  tr.low {{ background: #fdecea; }}
  td:nth-child(4) {{ width: 5rem; }}
</style>
</head>
<body>
<h1>Truth vs. Output Comparison</h1>
<p>Rows in red have a metric score below 0.5. Items sorted worst overall score first.</p>
{body}
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ground-truth-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None, help="Defaults to <output-root>/comparison_report.html")
    args = parser.parse_args()

    data_path = args.output_root / "comparison_data.json"
    if not data_path.is_file():
        print(f"Not found: {data_path}", file=sys.stderr)
        return 1

    comparison_data = json.loads(data_path.read_text(encoding="utf-8"))
    html = render_html(comparison_data, args.output_root, args.ground_truth_dir)

    report_path = args.report or (args.output_root / "comparison_report.html")
    report_path.write_text(html, encoding="utf-8")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
