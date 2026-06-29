"""Compare pipeline output across multiple ZAI models against Geoportal ground truth.

For each model and each input:
1. Runs the full pipeline (5 agents) with the specified model
2. Compares output to the human-reviewed Geoportal ground truth
3. Scores across 9 metrics (creators, ROR IDs, subjects, rights, etc.)

Outputs:
- reports/geoportal/comparison_data.json  — raw scores
- reports/geoportal/cross_model_comparison.md  — formatted report
- reports/geoportal/outputs/<model>/<input>.json  — raw pipeline outputs

Usage:
    uv run python scripts/compare_geoportal.py
    uv run python scripts/compare_geoportal.py --models glm-5.2,glm-5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

GEOPORTAL_DIR = Path("examples/Geoportal")
INPUTS_DIR = Path("tests/fixtures/geoportal/inputs")
REPORTS_DIR = Path("reports/geoportal")
CONFIG_PATH = Path("config/agents.yaml")
SCHEMA_NAME = "datacite-4.6"

DEFAULT_MODELS = "glm-5.2,glm-5.1,glm-5,glm-5-turbo,glm-4.7"

# Weights for overall score (must sum to 1.0)
WEIGHTS: dict[str, float] = {
    "creators_name": 0.20,
    "ror_match": 0.15,
    "subjects": 0.10,
    "categories": 0.10,
    "rights": 0.10,
    "languages": 0.05,
    "geo_places": 0.10,
    "media_formats": 0.05,
    "field_coverage": 0.15,
}


# ---------------------------------------------------------------------------
# Ground truth / pipeline execution
# ---------------------------------------------------------------------------

def load_ground_truth(geoportal_path: Path) -> dict[str, Any]:
    """Unwrap Geoportal output to extract just the DataCite attributes."""
    data = json.loads(geoportal_path.read_text(encoding="utf-8"))
    return data["metadata"]["attributes"]


def run_pipeline_for_model(
    input_path: Path, model: str, max_attempts: int = 3
) -> dict[str, Any] | None:
    """Run pipeline on a single input with the specified model.

    Retries up to *max_attempts* times. Between retries, does NOT reset the
    LLM client cache, so previously-successful agents are served from cache
    (instant) and only failed agents (no cache entry) get re-called. This
    handles reasoning-model flakiness where reasoning budget exhaustion
    causes empty content → Instructor parse failure.

    Returns the output with the highest field coverage across all attempts,
    or None if every attempt failed.
    """
    # Lazy imports — avoid heavy startup if just generating report
    from metadata_enricher.config.loader import load_config
    from metadata_enricher.input_sources.filesystem import FilesystemInputSource
    from metadata_enricher.llm.factory import create_llm_client
    from metadata_enricher.output import OutputWriter
    from metadata_enricher.pipeline import Pipeline
    from metadata_enricher.schemas import get_registry

    config = load_config(CONFIG_PATH)

    # Override all agents to use target model + zai-coding-plan provider
    for agent in config.agents:
        agent.model = model
        agent.provider = "zai-coding-plan"

    # Per-model cache directory
    cache_dir = REPORTS_DIR / "cache" / model.replace(".", "_")
    cache_dir.mkdir(parents=True, exist_ok=True)

    def llm_factory(provider: str, model: str, **kwargs: Any) -> Any:
        return create_llm_client(provider, model, cache_dir=cache_dir, **kwargs)

    pipeline = Pipeline(config=config, llm_factory=llm_factory)
    source = FilesystemInputSource()

    schema = get_registry().get(SCHEMA_NAME)
    writer = OutputWriter(schema=schema)

    best_output: dict[str, Any] | None = None
    best_field_count = 0

    for attempt in range(1, max_attempts + 1):
        results = pipeline.run(source, pattern=str(input_path))

        if not results or not results[0].success:
            continue

        json_str = writer.format_json(results[0].document)
        output = json.loads(json_str)
        field_count = len(extract_populated_fields(output))

        if field_count > best_field_count:
            best_output = output
            best_field_count = field_count

        # 18 possible DataCite field groups; ≥12 is solid coverage
        if best_field_count >= 12:
            break

    return best_output


# ---------------------------------------------------------------------------
# Extraction helpers — normalize both ground truth and pipeline output
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return s.strip().lower()


def extract_creator_names(attrs: dict) -> set[str]:
    return {
        _norm(c["creator_name"])
        for c in attrs.get("creators", [])
        if c.get("creator_name", "").strip()
    }


def extract_ror_ids(attrs: dict) -> set[str]:
    rors: set[str] = set()
    for c in attrs.get("creators", []):
        for nid in c.get("name_identifiers", []):
            if nid.get("name_identifier_scheme") == "ROR":
                val = nid.get("name_identifier", "").strip().lower()
                if val:
                    rors.add(val)
        for aff in c.get("affiliations", []):
            if aff.get("affiliation_identifier_scheme") == "ROR":
                val = aff.get("affiliation_identifier", "").strip().lower()
                if val:
                    rors.add(val)
    for p in attrs.get("publishers", []):
        if p.get("publisher_identifier_scheme") == "ROR":
            val = p.get("publisher_identifier", "").strip().lower()
            if val:
                rors.add(val)
    return rors


def extract_subjects(attrs: dict) -> set[str]:
    return {
        _norm(s["subject_name"])
        for s in attrs.get("subjects", [])
        if s.get("subject_name", "").strip()
    }


def extract_categories(attrs: dict) -> set[str]:
    return {
        f"{_norm(c.get('name', ''))}|{_norm(c.get('sub_category', ''))}"
        for c in attrs.get("categories", [])
        if c.get("name", "").strip()
    }


def extract_rights_id(attrs: dict) -> str:
    rights = attrs.get("rights", [])
    if rights and isinstance(rights, list):
        return _norm(rights[0].get("rights_identifier", ""))
    return ""


def extract_languages(attrs: dict) -> set[str]:
    return {
        _norm(lang["lang_code"])
        for lang in attrs.get("languages", [])
        if lang.get("lang_code", "").strip()
    }


def extract_geo_places(attrs: dict) -> set[str]:
    """Handle both flat geo_locations and nested temporal_geo.geo_locations."""
    if "temporal_geo" in attrs:
        tg = attrs["temporal_geo"]
        geos = tg.get("geo_locations", []) if isinstance(tg, dict) else []
    else:
        geos = attrs.get("geo_locations", [])
    return {
        _norm(g.get("geo_location_place", ""))
        for g in geos
        if g.get("geo_location_place", "").strip()
    }


def extract_media_formats(attrs: dict) -> set[str]:
    return {
        _norm(m["format"])
        for m in attrs.get("media_files", [])
        if m.get("format", "").strip()
    }


def extract_populated_fields(attrs: dict) -> set[str]:
    return {
        k for k, v in attrs.items()
        if v is not None and v != [] and v != {}
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def compare_outputs(truth: dict, actual: dict) -> dict[str, float]:
    scores: dict[str, float] = {}

    scores["creators_name"] = jaccard(
        extract_creator_names(truth), extract_creator_names(actual)
    )

    truth_rors = extract_ror_ids(truth)
    actual_rors = extract_ror_ids(actual)
    if truth_rors:
        scores["ror_match"] = len(truth_rors & actual_rors) / len(truth_rors)
    elif actual_rors:
        scores["ror_match"] = 0.0  # hallucinated RORs not in ground truth
    else:
        scores["ror_match"] = 1.0

    scores["subjects"] = jaccard(
        extract_subjects(truth), extract_subjects(actual)
    )
    scores["categories"] = jaccard(
        extract_categories(truth), extract_categories(actual)
    )

    scores["rights"] = (
        1.0 if extract_rights_id(truth) and extract_rights_id(truth) == extract_rights_id(actual)
        else 0.0
    )

    scores["languages"] = jaccard(
        extract_languages(truth), extract_languages(actual)
    )
    scores["geo_places"] = jaccard(
        extract_geo_places(truth), extract_geo_places(actual)
    )
    scores["media_formats"] = jaccard(
        extract_media_formats(truth), extract_media_formats(actual)
    )

    truth_fields = extract_populated_fields(truth)
    actual_fields = extract_populated_fields(actual)
    scores["field_coverage"] = (
        len(truth_fields & actual_fields) / len(truth_fields) if truth_fields else 0.0
    )

    scores["overall"] = sum(scores[k] * w for k, w in WEIGHTS.items())
    return scores


# ---------------------------------------------------------------------------
# Main comparison runner
# ---------------------------------------------------------------------------

def run_comparison(models: list[str]) -> dict:
    input_files = sorted(INPUTS_DIR.glob("*.json"))
    if not input_files:
        print("No inputs found. Run generate_geoportal_inputs.py first.", file=sys.stderr)
        sys.exit(1)

    all_results: dict[str, Any] = {"models": {}}

    for mi, model in enumerate(models):
        print(f"\n{'=' * 60}")
        print(f"  Model {mi + 1}/{len(models)}: {model}")
        print(f"{'=' * 60}")

        from metadata_enricher.llm.factory import reset_client_cache
        reset_client_cache()

        model_results: list[dict] = []

        for ii, input_path in enumerate(input_files):
            label = input_path.stem[:50]
            print(f"  [{ii + 1}/{len(input_files)}] {label}...", end=" ", flush=True)
            t0 = time.time()

            gt_path = GEOPORTAL_DIR / input_path.name
            if not gt_path.exists():
                print("SKIP (no ground truth)")
                continue

            truth = load_ground_truth(gt_path)

            try:
                actual = run_pipeline_for_model(input_path, model, max_attempts=3)
            except Exception as e:
                print(f"ERROR ({e})")
                model_results.append({"input": input_path.name, "error": str(e), "scores": {}})
                continue

            if actual is None:
                print("FAIL (empty)")
                model_results.append({"input": input_path.name, "error": "empty output", "scores": {}})
                continue

            scores = compare_outputs(truth, actual)
            elapsed = time.time() - t0
            n_fields = len(extract_populated_fields(actual))
            print(f"overall={scores['overall']:.3f} fields={n_fields}/18 ({elapsed:.0f}s)")

            # Save raw output
            out_dir = REPORTS_DIR / "outputs" / model.replace(".", "_")
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / input_path.name).write_text(
                json.dumps(actual, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            model_results.append({
                "input": input_path.name,
                "scores": scores,
                "elapsed_s": round(elapsed, 1),
            })

        valid = [r for r in model_results if r.get("scores")]
        if valid:
            avg = sum(r["scores"]["overall"] for r in valid) / len(valid)
            all_results["models"][model] = {"avg_overall": round(avg, 3), "results": model_results}
            print(f"\n  → {model} average: {avg:.3f} ({len(valid)}/{len(input_files)} succeeded)")

            # Save partial results after each model
            (REPORTS_DIR / "comparison_data.json").write_text(
                json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    return all_results


def generate_report(results: dict) -> str:
    lines = ["# Geoportal Model Comparison Report\n"]
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    models = list(results["models"].keys())
    if not models:
        lines.append("No results.\n")
        return "\n".join(lines)

    # ---- Summary table
    lines.append("## Summary\n")
    cols = ["avg_overall", "creators_name", "ror_match", "subjects",
            "categories", "rights", "field_coverage"]
    header = "| Model | " + " | ".join(c.replace("_", " ").title() for c in cols) + " |"
    sep = "|---" * (len(cols) + 1) + "|"
    lines.append(header)
    lines.append(sep)

    for model in models:
        mdata = results["models"][model]
        valid = [r for r in mdata["results"] if r.get("scores")]
        if not valid:
            continue

        def avg(key: str) -> str:
            vals = [r["scores"].get(key, 0) for r in valid]
            return f"{sum(vals) / len(vals):.3f}"

        row = f"| **{model}** | {mdata['avg_overall']:.3f} | "
        row += " | ".join(avg(c) for c in cols[1:])
        lines.append(row + " |")

    # ---- Per-input detail
    lines.append("\n## Per-Input Detail\n")
    input_names = [r["input"] for r in results["models"][models[0]]["results"]]

    for inp in input_names:
        lines.append(f"### {inp}\n")
        h = "| Metric |" + "|".join(f" {m} " for m in models) + "|"
        s = "|---" * (len(models) + 1) + "|"
        lines.append(h)
        lines.append(s)

        for metric in ["overall"] + list(WEIGHTS.keys()):
            row = f"| {metric} |"
            for model in models:
                mdata = results["models"].get(model, {})
                match = [r for r in mdata.get("results", []) if r["input"] == inp]
                if match and match[0].get("scores"):
                    row += f" {match[0]['scores'].get(metric, 0):.3f} |"
                else:
                    row += " — |"
            lines.append(row)
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    # Suppress .env leak for non-pipeline operations
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    parser = argparse.ArgumentParser(
        description="Compare pipeline output across ZAI models vs Geoportal ground truth."
    )
    parser.add_argument(
        "--models", default=DEFAULT_MODELS,
        help=f"Comma-separated model names (default: {DEFAULT_MODELS})"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        print("No models specified.", file=sys.stderr)
        sys.exit(1)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Models: {', '.join(models)}")
    print(f"Inputs: {INPUTS_DIR}/")
    print(f"Reports: {REPORTS_DIR}/")

    results = run_comparison(models)
    report = generate_report(results)
    report_path = REPORTS_DIR / "cross_model_comparison.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
