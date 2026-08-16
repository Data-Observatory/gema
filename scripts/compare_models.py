#!/usr/bin/env python3
"""Structural (Jaccard-vs-truth) comparison across models/providers, for any
corpus — parameterized entirely by --ground-truth-dir/--inputs-dir/--output-root,
no hardcoded corpus assumptions in this script itself.

Ground truth is adapted via do_catalog_common.adapt_ground_truth() before
scoring (roles -> creators, scheme-aware identifier matching) — this script
is written for the do_catalog corpus specifically (hence importing that
module by name), but nothing about its own logic assumes a particular
directory layout.

Usage:
    uv run python scripts/compare_models.py \
        --ground-truth-dir tests/fixtures/do_catalog/ground_truth \
        --inputs-dir tests/fixtures/do_catalog/inputs \
        --output-root reports/do_catalog/pilot \
        --models zai-coding-plan:glm-5.3,zai-coding-plan:glm-5-turbo,opencode:deepseek-v4-flash
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import do_catalog_common
import eval_common
from dotenv import load_dotenv

load_dotenv()


def load_manifest_titles(ground_truth_dir: Path) -> dict[str, str]:
    """Best-effort lookup of original_title by final_filename, from the
    sibling manifest.json (if present) — purely cosmetic, for report rows."""
    manifest_path = ground_truth_dir.parent / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {e["final_filename"]: e.get("original_title", "") for e in manifest}


def run_comparison(
    models: list[str], ground_truth_dir: Path, inputs_dir: Path, output_root: Path,
    *, enrich: bool = False, limit: int | None = None, rescore_only: bool = False,
) -> dict[str, Any]:
    input_files = sorted(inputs_dir.glob("*.json"))
    if limit is not None:
        input_files = input_files[:limit]
    if not input_files:
        print(f"No inputs found in {inputs_dir}", file=sys.stderr)
        sys.exit(1)

    all_results: dict[str, Any] = {"models": {}}

    for mi, spec in enumerate(models):
        provider, model = eval_common.parse_model_spec(spec)
        label = eval_common.sanitize_label(spec)

        print(f"\n{'=' * 60}\n  Model {mi + 1}/{len(models)}: {spec} (provider={provider})\n{'=' * 60}")

        from metadata_enricher.llm.factory import reset_client_cache
        reset_client_cache()

        def _process(ii: int, input_path: Path) -> dict[str, Any]:
            gt_path = ground_truth_dir / input_path.name
            if not gt_path.exists():
                print(f"  [{ii + 1}/{len(input_files)}] {input_path.stem[:50]}... SKIP (no ground truth)")
                return {"input": input_path.name, "error": "no ground truth", "scores": {}}

            truth_raw = json.loads(gt_path.read_text(encoding="utf-8"))
            truth = do_catalog_common.adapt_ground_truth(truth_raw)

            prefix = f"  [{ii + 1}/{len(input_files)}] {input_path.stem[:50]}..."

            saved_path = output_root / "outputs" / label / input_path.name
            rescored = rescore_only and saved_path.exists()
            note = ""
            if rescored:
                # Rescoring an already-saved output -- no pipeline call, so
                # "elapsed" would just measure a file read, not real latency.
                # Reported as "(rescored)" instead of a misleading "(0s)".
                actual = json.loads(saved_path.read_text(encoding="utf-8"))
            else:
                if rescore_only:
                    note = " [no saved output, ran pipeline]"
                t0 = time.time()
                try:
                    actual = eval_common.run_pipeline_for_model(
                        input_path, provider, model, output_root,
                        enrich=enrich, max_attempts=3, cache_label=label,
                    )
                except Exception as e:
                    print(f"{prefix} ERROR ({e})")
                    return {"input": input_path.name, "error": str(e), "scores": {}}

                if actual is None:
                    print(f"{prefix} FAIL (empty)")
                    return {"input": input_path.name, "error": "empty output", "scores": {}}

                out_dir = output_root / "outputs" / label
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / input_path.name).write_text(
                    json.dumps(actual, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                elapsed = time.time() - t0

            scores = do_catalog_common.compare_outputs(truth, actual)
            n_fields = len(eval_common.extract_populated_fields(actual))
            timing = "(rescored)" if rescored else f"({elapsed:.0f}s)"
            print(f"{prefix}{note} overall={scores['overall']:.3f} orcid={scores['orcid_match']:.3f} "
                  f"fields={n_fields}/18 {timing}")

            result: dict[str, Any] = {"input": input_path.name, "scores": scores}
            if not rescored:
                result["elapsed_s"] = round(elapsed, 1)
            return result

        # Cross-item concurrency here tracks the same config-driven
        # global/provider/model cascade used for per-resource agent
        # concurrency (config/providers.yaml) — no hardcoded provider name.
        # A provider/model resolving to max_workers <= 1 (e.g.
        # zai-coding-plan's tight account rate limit) stays fully
        # sequential; anything above that runs items concurrently, capped
        # at 3 to avoid multiplying total in-flight requests too far past
        # what was actually verified safe. Order of completion is not
        # preserved (prints interleave) but model_results is re-sorted back
        # to input order before scoring, so reports are unaffected.
        item_workers = min(eval_common.resolve_max_workers(provider, model), 3)
        if item_workers > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=item_workers) as executor:
                futures = {
                    executor.submit(_process, ii, input_path): ii
                    for ii, input_path in enumerate(input_files)
                }
                indexed_results = sorted(
                    ((futures[f], f.result()) for f in futures), key=lambda pair: pair[0]
                )
            model_results = [r for _, r in indexed_results]
        else:
            model_results = [_process(ii, input_path) for ii, input_path in enumerate(input_files)]

        valid = [r for r in model_results if r.get("scores")]
        if valid:
            avg = sum(r["scores"]["overall"] for r in valid) / len(valid)
            all_results["models"][spec] = {"avg_overall": round(avg, 3), "results": model_results}
            print(f"\n  → {spec} average: {avg:.3f} ({len(valid)}/{len(input_files)} succeeded)")

        (output_root / "comparison_data.json").write_text(
            json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return all_results


def generate_report(results: dict[str, Any], ground_truth_dir: Path) -> str:
    titles = load_manifest_titles(ground_truth_dir)
    lines = ["# Structural Model Comparison Report\n", f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"]

    models = list(results["models"].keys())
    if not models:
        lines.append("No results.\n")
        return "\n".join(lines)

    cols = ["avg_overall", "creators_name", "ror_match", "orcid_match", "subjects",
            "categories", "rights", "field_coverage"]
    lines.append("## Summary\n")
    lines.append("| Model | " + " | ".join(c.replace("_", " ").title() for c in cols) + " |")
    lines.append("|---" * (len(cols) + 1) + "|")

    for model in models:
        mdata = results["models"][model]
        valid = [r for r in mdata["results"] if r.get("scores")]
        if not valid:
            continue

        def avg(key: str) -> str:
            vals = [r["scores"].get(key, 0) for r in valid]
            return f"{sum(vals) / len(vals):.3f}"

        row = f"| **{model}** | {mdata['avg_overall']:.3f} | " + " | ".join(avg(c) for c in cols[1:])
        lines.append(row + " |")

    lines.append("\n## Per-Input Detail\n")
    input_names = [r["input"] for r in results["models"][models[0]]["results"]]

    for inp in input_names:
        title = titles.get(inp, "")
        header = f"### {inp}" + (f" — {title}" if title else "")
        lines.append(f"{header}\n")
        lines.append("| Metric |" + "|".join(f" {m} " for m in models) + "|")
        lines.append("|---" * (len(models) + 1) + "|")

        for metric in ["overall", *eval_common.WEIGHTS.keys(), "orcid_match"]:
            row = f"| {metric} |"
            for model in models:
                mdata = results["models"].get(model, {})
                match = [r for r in mdata.get("results", []) if r["input"] == inp]
                row += f" {match[0]['scores'].get(metric, 0):.3f} |" if match and match[0].get("scores") else " — |"
            lines.append(row)
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ground-truth-dir", type=Path, required=True)
    parser.add_argument("--inputs-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--models", required=True, help="Comma-separated provider:model specs")
    parser.add_argument("--limit", type=int, default=None, help="Cap number of inputs (e.g. for a smoke test)")
    parser.add_argument("--enrich", action="store_true", default=False,
                         help="Force identifier enrichment on (it's already on by default via config)")
    parser.add_argument(
        "--rescore-only", action="store_true", default=False,
        help=(
            "Re-score already-saved outputs (output-root/outputs/<label>/*.json) "
            "instead of re-running the pipeline -- zero live-API cost. Falls back "
            "to a normal pipeline run for any input with no saved output."
        ),
    )
    args = parser.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    args.output_root.mkdir(parents=True, exist_ok=True)

    print(f"Models: {', '.join(models)}")
    print(f"Ground truth: {args.ground_truth_dir}/")
    print(f"Inputs: {args.inputs_dir}/")
    print(f"Output: {args.output_root}/")

    results = run_comparison(
        models, args.ground_truth_dir, args.inputs_dir, args.output_root,
        enrich=args.enrich, limit=args.limit, rescore_only=args.rescore_only,
    )
    report = generate_report(results, args.ground_truth_dir)
    report_path = args.output_root / "structural_comparison.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
