#!/usr/bin/env python3
"""LLM-as-judge scoring across models, reading compare_models.py's already-saved
raw outputs instead of re-running the pipeline — running it twice would double
the real cost and confound the structural-vs-judge agreement check with
run-to-run nondeterminism (identifier enrichment is live/uncached).

Builds the judge client once (fixed across all candidate models). If DeepEval's
GEval fails for one model/input but not another, that is recorded explicitly
as a per-input error — NOT silently substituted with the per-field fallback
score presented as an equivalent "overall". A report mixing two different
judges without saying so is worse than no report.

Usage:
    uv run python scripts/judge_models.py \
        --ground-truth-dir tests/fixtures/do_catalog/ground_truth \
        --inputs-dir tests/fixtures/do_catalog/inputs \
        --output-root reports/do_catalog/pilot \
        --models zai-coding-plan:glm-5.2,zai-coding-plan:glm-5-turbo,opencode:deepseek-v4-flash \
        --judge opencode:qwen3.7-plus
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import do_catalog_common
import eval_common
from dotenv import load_dotenv

load_dotenv()


def spearman_correlation(a: list[float], b: list[float]) -> float | None:
    """Manual Spearman rank correlation (no scipy dependency). Returns None
    if fewer than 2 paired points or either series has zero variance."""
    n = len(a)
    if n < 2:
        return None

    def rank(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        ranks = [0.0] * len(xs)
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    ra, rb = rank(a), rank(b)
    mean_ra, mean_rb = sum(ra) / n, sum(rb) / n
    cov: float = sum((x - mean_ra) * (y - mean_rb) for x, y in zip(ra, rb, strict=True))
    var_a: float = sum((x - mean_ra) ** 2 for x in ra)
    var_b: float = sum((y - mean_rb) ** 2 for y in rb)
    if var_a == 0 or var_b == 0:
        return None
    return float(cov / (var_a * var_b) ** 0.5)


def _find_provider(config: Any, name: str) -> Any:
    for p in config.providers:
        if p.name == name:
            return p
    msg = f"Provider '{name}' not found in config"
    raise ValueError(msg)


def run_judging(
    models: list[str], ground_truth_dir: Path, inputs_dir: Path, output_root: Path, judge_spec: str,
) -> dict[str, Any]:
    from metadata_enricher.config.loader import load_config
    from metadata_enricher.llm.factory import create_llm_client

    config = load_config(eval_common.CONFIG_PATH)
    judge_provider_name, judge_model = eval_common.parse_model_spec(judge_spec)
    judge_provider = _find_provider(config, judge_provider_name)
    judge_api_key = os.environ[judge_provider.api_key_env]

    # Deliberately NOT applying MODEL_EXTRA_BODY here: that table exists for
    # the forced-tool_choice structured-output path (Instructor's .complete()),
    # which the judge never uses. Its actual paths — complete_raw() and
    # GEval's own logprobs-based call — were confirmed this session to work
    # fine without any override for qwen3.7-plus. Applying it anyway broke
    # GEval outright: DeepEval's GPTModel(generation_kwargs=...) forwards the
    # dict as top-level kwargs to the OpenAI call, not nested under
    # extra_body, so {"thinking": {...}} surfaced as an unexpected keyword
    # argument rather than reaching the API in the shape the model expects.
    judge_client = create_llm_client(
        judge_provider, model=judge_model, temperature=0.0, max_tokens=4096,
        use_cache=False, use_retry=True,
    )

    input_files = sorted(inputs_dir.glob("*.json"))
    all_results: dict[str, Any] = {"judge": judge_spec, "models": {}}

    for mi, spec in enumerate(models):
        label = eval_common.sanitize_label(spec)
        print(f"\n{'=' * 60}\n  Judging {mi + 1}/{len(models)}: {spec}\n{'=' * 60}")

        def _judge_one(ii: int, input_path: Path) -> dict[str, Any] | None:
            stem = input_path.name
            actual_path = output_root / "outputs" / label / stem
            gt_path = ground_truth_dir / stem
            if not actual_path.exists() or not gt_path.exists():
                print(f"  [{ii + 1}/{len(input_files)}] {stem}... SKIP (no saved output or ground truth)")
                return None

            actual_json = actual_path.read_text(encoding="utf-8")
            truth_raw = json.loads(gt_path.read_text(encoding="utf-8"))
            truth_adapted = do_catalog_common.adapt_ground_truth(truth_raw)
            expected_json = json.dumps(truth_adapted, ensure_ascii=False)
            resource_json = input_path.read_text(encoding="utf-8")

            print(f"  [{ii + 1}/{len(input_files)}] {stem[:50]}...", end=" ", flush=True)

            geval_score: float | None = None
            geval_reason = ""
            geval_error: str | None = None
            try:
                geval_score, geval_reason = eval_common.score_overall_deepeval(
                    actual_json=actual_json, expected_json=expected_json, resource_json=resource_json,
                    judge_model=judge_model, api_key=judge_api_key, base_url=judge_provider.base_url,
                )
            except Exception as exc:
                geval_error = str(exc)

            field_overall, field_scores, notes = eval_common.score_per_field_raw(
                judge_client=judge_client, actual_json=actual_json,
                expected_json=expected_json, resource_json=resource_json,
            )

            if geval_error is not None:
                print(f"GEval FAILED ({geval_error[:80]}) — field_overall={field_overall:.3f}")
            else:
                print(f"geval={geval_score:.3f} field_overall={field_overall:.3f}")

            return {
                "input": stem,
                "geval_score": geval_score,
                "geval_reason": geval_reason,
                "geval_error": geval_error,
                "field_overall": field_overall,
                "field_scores": field_scores,
                "notes": notes,
            }

        # Every judging call goes to the judge client (judge_provider_name/
        # judge_model), regardless of which candidate model's outputs are
        # being scored — resolve concurrency against the judge's own
        # provider/model, same config-driven cascade as compare_models.py,
        # no hardcoded provider name.
        item_workers = min(eval_common.resolve_max_workers(judge_provider_name, judge_model), 3)
        if item_workers > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=item_workers) as executor:
                futures = {
                    executor.submit(_judge_one, ii, input_path): ii
                    for ii, input_path in enumerate(input_files)
                }
                indexed_results = sorted(
                    ((futures[f], f.result()) for f in futures), key=lambda pair: pair[0]
                )
            model_results = [r for _, r in indexed_results if r is not None]
        else:
            model_results = [
                r for ii, input_path in enumerate(input_files)
                if (r := _judge_one(ii, input_path)) is not None
            ]

        succeeded = [r for r in model_results if r["geval_error"] is None]
        n_failed = len(model_results) - len(succeeded)
        avg_geval = sum(r["geval_score"] for r in succeeded) / len(succeeded) if succeeded else None
        all_results["models"][spec] = {
            "avg_geval": round(avg_geval, 3) if avg_geval is not None else None,
            "geval_failures": n_failed,
            "results": model_results,
        }
        if n_failed:
            print(f"\n  ⚠ {spec}: GEval failed on {n_failed}/{len(model_results)} inputs — see geval_error per input")

        (output_root / "judge_data.json").write_text(
            json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return all_results


def generate_report(judge_results: dict[str, Any], structural_data_path: Path) -> str:
    lines = ["# LLM-as-Judge Model Comparison Report\n"]
    lines.append(f"**Judge model:** {judge_results['judge']}\n")

    models = list(judge_results["models"].keys())
    if not models:
        lines.append("No results.\n")
        return "\n".join(lines)

    lines.append("## Summary\n")
    lines.append("| Model | Avg GEval | GEval Failures |")
    lines.append("|---|---|---|")
    for spec in models:
        mdata = judge_results["models"][spec]
        avg = f"{mdata['avg_geval']:.3f}" if mdata["avg_geval"] is not None else "N/A"
        lines.append(f"| **{spec}** | {avg} | {mdata['geval_failures']} |")

    structural: dict[str, Any] | None = None
    if structural_data_path.exists():
        structural = json.loads(structural_data_path.read_text(encoding="utf-8"))

    if structural:
        lines.append("\n## Structural vs Judge Agreement\n")
        lines.append(
            "Spearman rank correlation between the structural `overall` score and "
            "GEval's score, per model — a large, unexplained disagreement is itself "
            "a signal something's off in the adapter or the judge prompt, not just "
            "\"the models disagree.\"\n"
        )
        lines.append("| Model | Spearman ρ | N |")
        lines.append("|---|---|---|")

        for spec in models:
            struct_by_input = {
                r["input"]: r["scores"]["overall"]
                for r in structural.get("models", {}).get(spec, {}).get("results", [])
                if r.get("scores")
            }
            judge_by_input = {
                r["input"]: r["geval_score"]
                for r in judge_results["models"][spec]["results"]
                if r["geval_score"] is not None
            }
            common_inputs = sorted(set(struct_by_input) & set(judge_by_input))
            if len(common_inputs) < 2:
                lines.append(f"| **{spec}** | N/A | {len(common_inputs)} |")
                continue

            struct_vals = [struct_by_input[i] for i in common_inputs]
            judge_vals = [judge_by_input[i] for i in common_inputs]
            rho = spearman_correlation(struct_vals, judge_vals)
            rho_str = f"{rho:.3f}" if rho is not None else "N/A"
            lines.append(f"| **{spec}** | {rho_str} | {len(common_inputs)} |")

            diffs = sorted(
                ((abs(struct_by_input[i] - judge_by_input[i]), i) for i in common_inputs),
                reverse=True,
            )[:5]
            if diffs:
                lines.append(f"\n**Largest disagreements for {spec}:**\n")
                lines.append("| Input | Structural | GEval | Judge notes |")
                lines.append("|---|---|---|---|")
                for _diff, inp in diffs:
                    match = [r for r in judge_results["models"][spec]["results"] if r["input"] == inp]
                    reason = match[0]["geval_reason"][:150] if match else ""
                    lines.append(
                        f"| {inp} | {struct_by_input[inp]:.3f} | {judge_by_input[inp]:.3f} | {reason} |"
                    )
                lines.append("")

    lines.append("\n## Per-Input Detail\n")
    for spec in models:
        lines.append(f"### {spec}\n")
        for r in judge_results["models"][spec]["results"]:
            lines.append(f"**{r['input']}**")
            if r["geval_error"] is not None:
                lines.append(f"- GEval: FAILED — `{r['geval_error'][:200]}`")
            else:
                lines.append(f"- GEval: {r['geval_score']:.3f} — {r['geval_reason'][:200]}")
            lines.append(f"- Per-field overall: {r['field_overall']:.3f}")
            if r["notes"]:
                lines.append(f"- Notes: {r['notes']}")
            lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ground-truth-dir", type=Path, required=True)
    parser.add_argument("--inputs-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True,
                         help="Same --output-root passed to compare_models.py — reads its saved outputs")
    parser.add_argument("--models", required=True, help="Comma-separated provider:model specs")
    parser.add_argument("--judge", required=True, help="provider:model for the judge")
    args = parser.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    args.output_root.mkdir(parents=True, exist_ok=True)

    print(f"Judge: {args.judge}")
    print(f"Models: {', '.join(models)}")
    print(f"Reading saved outputs from: {args.output_root}/outputs/")

    results = run_judging(models, args.ground_truth_dir, args.inputs_dir, args.output_root, args.judge)
    report = generate_report(results, args.output_root / "comparison_data.json")
    report_path = args.output_root / "judge_comparison.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport: {report_path}")

    total_failures = sum(m["geval_failures"] for m in results["models"].values())
    if total_failures:
        print(f"\n⚠ {total_failures} GEval failure(s) across all models — see judge_comparison.md", file=sys.stderr)


if __name__ == "__main__":
    main()
