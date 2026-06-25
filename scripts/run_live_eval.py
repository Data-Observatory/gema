#!/usr/bin/env python3
"""Live evaluator: run Pipeline with real API, score vs golden outputs, write report.

Runs the full metagen Pipeline against every input in the golden inputs directory,
compares the actual output (fresh API calls, no cache replay) to the expected
output via LLM-as-judge semantic scoring, and writes a Markdown report to ``reports/``.

**Scorer:** DeepEval ``GEval`` (primary, overall semantic quality) + hand-rolled
per-field LLM-as-judge using ``complete_raw()`` (per-field breakdown + notes).
DeepEval was chosen because it installed and imported cleanly (v4.0.7).
The hand-rolled supplement provides the field-level breakdown that GEval alone
cannot produce.

**Prerequisites:**
    Set the API key env var referenced by the default provider in your config.
    Example: ``export ZAI_API_KEY=...`` (or OPENAI_API_KEY, OPENCODE_API_KEY, etc.)

    Populate expected outputs first:
        uv run python scripts/record_golden.py
        ── or ──
        make record-golden

**Usage:**
    uv run python scripts/run_live_eval.py
    uv run python scripts/run_live_eval.py --config config/agents.yaml --verbose
    uv run python scripts/run_live_eval.py -i tests/fixtures/golden/inputs -e tests/fixtures/golden/expected --threshold 0.80

**Output:**
    Writes ``reports/live_eval_<timestamp>.md`` with per-input scores, per-field
    breakdown, and overall summary.

**Exit codes:**
    0 = mean score >= threshold (PASS)
    1 = mean score < threshold (FAIL) or partial failure
    2 = environment not configured
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from metadata_enricher.agents.registry import LLMClientFactory
from metadata_enricher.config.loader import load_config
from metadata_enricher.config.models import PipelineConfig, ProviderConfig
from metadata_enricher.input_sources.filesystem import FilesystemInputSource
from metadata_enricher.llm.base import LLMClient
from metadata_enricher.llm.factory import create_llm_client, reset_client_cache
from metadata_enricher.output import OutputWriter
from metadata_enricher.pipeline import Pipeline, PipelineResult
from metadata_enricher.schemas import get_registry
from metadata_enricher.schemas.base import Schema

logger = logging.getLogger(__name__)

# ── Scoring prompt template (used for per-field breakdown) ──────────────────

_SCORING_PROMPT = """\
You are a metadata quality evaluator for DataCite 4.6 metadata records.
Your task: compare a CANDIDATE metadata output against a REFERENCE (golden) output,
given the original RESOURCE description as context.

=== RESOURCE DESCRIPTION (what the metadata describes) ===
{resource_description}

=== REFERENCE OUTPUT (golden expected) ===
{expected_output}

=== CANDIDATE OUTPUT (actual from pipeline) ===
{actual_output}

For each top-level metadata field present in either the reference or the candidate,
score the candidate on a 0.0–1.0 scale considering:

1. **Accuracy** — Does the candidate contain correct values (no hallucinations)?
2. **Completeness** — Does the candidate capture all fields present in the reference?
3. **Coherence** — Is the candidate's data logically consistent and well-structured?

The score for each field should be the average of these three dimensions.
Extra fields in the candidate beyond the reference are notes but do NOT penalize the score
unless they contain fabricated data.

Return a JSON object with these keys:
- "overall": float (0.0–1.0) — mean of all field scores, weighted equally
- "fields": object mapping field_name (string) to score (float 0.0–1.0)
- "notes": string — brief qualitative observations (max 300 chars)

Respond with ONLY the JSON object. No markdown fences, no surrounding text."""


@dataclass
class ScoredResult:
    """Result of scoring one input against its expected output."""

    input_stem: str
    overall: float
    field_scores: dict[str, float]
    notes: str
    deepeval_score: float | None = None
    deepeval_reason: str | None = None


@dataclass
class EvalReport:
    """Aggregate report for all evaluated inputs."""

    timestamp: str
    production_model: str
    judge_model: str
    provider_name: str
    config_path: str
    inputs_dir: str
    threshold: float
    results: list[ScoredResult] = field(default_factory=list)

    @property
    def mean_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.overall for r in self.results) / len(self.results)

    @property
    def min_result(self) -> ScoredResult | None:
        return min(self.results, key=lambda r: r.overall) if self.results else None

    @property
    def max_result(self) -> ScoredResult | None:
        return max(self.results, key=lambda r: r.overall) if self.results else None


# ── Helpers (mirror record_golden.py style) ─────────────────────────────────


def _make_factory(cache_dir: Path) -> LLMClientFactory:
    """Create an LLMClientFactory that uses *cache_dir* for all clients."""

    def _factory(
        provider: ProviderConfig,
        model: str,
        temperature: float,
        max_tokens: int | None,
    ) -> LLMClient:
        return create_llm_client(
            provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            cache_dir=cache_dir,
        )

    return _factory


def _find_default_provider(config: PipelineConfig) -> ProviderConfig:
    """Return the default provider from config.

    Checks ``default_provider`` field first, then falls back to the first
    provider marked ``default: true``, then the first provider in the list.
    """
    if config.default_provider:
        for p in config.providers:
            if p.name == config.default_provider:
                return p

    for p in config.providers:
        if p.default:
            return p

    return config.providers[0]


def _check_api_key(provider: ProviderConfig) -> None:
    """Verify the API key env var for *provider* is set. Exit 2 if not."""
    if not os.environ.get(provider.api_key_env):
        print(
            f"ERROR: Environment variable '{provider.api_key_env}' is not set.\n"
            f"       This is required by the default provider '{provider.name}'.\n"
            f"       Example: export {provider.api_key_env}=...",
            file=sys.stderr,
        )
        sys.exit(2)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live evaluator: run Pipeline with real API, score vs golden outputs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 = PASS, 1 = FAIL, 2 = env not configured.",
    )
    parser.add_argument(
        "-c", "--config",
        default="config/agents.yaml",
        help="Path to pipeline config YAML (default: config/agents.yaml)",
    )
    parser.add_argument(
        "-i", "--inputs",
        default="tests/fixtures/golden/inputs",
        help="Directory with input JSON files (default: tests/fixtures/golden/inputs)",
    )
    parser.add_argument(
        "-e", "--expected",
        default="tests/fixtures/golden/expected",
        help="Directory with expected golden outputs (default: tests/fixtures/golden/expected)",
    )
    parser.add_argument(
        "--reports-dir",
        default="reports",
        help="Directory for evaluation reports (default: reports)",
    )
    parser.add_argument(
        "-s", "--schema",
        default="datacite-4.6",
        help="Schema name to use (default: datacite-4.6)",
    )
    parser.add_argument(
        "--model",
        default="glm-5.2",
        help="Model for the judge LLM — may differ from production model (default: glm-5.2)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="PASS/FAIL threshold for mean overall score (default: 0.75)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return parser.parse_args(argv)


# ── DeepEval overall scorer ──────────────────────────────────────────────────


def _score_overall_deepeval(
    *,
    actual_json: str,
    expected_json: str,
    resource_json: str,
    judge_model: str,
    api_key: str,
    base_url: str | None,
) -> tuple[float, str]:
    """Score overall semantic quality using DeepEval GEval.

    Returns (score, reason). Raises on failure (treated as non-fatal upstream).
    """
    from deepeval.metrics import GEval  # noqa: PLC0415 — optional dep
    from deepeval.models import GPTModel  # noqa: PLC0415
    from deepeval.test_case import LLMTestCase  # noqa: PLC0415

    gpt_model = GPTModel(
        model=judge_model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
    )

    metric = GEval(
        name="DataCite Semantic Quality",
        criteria=(
            "Evaluate if the candidate DataCite 4.6 metadata is accurate, complete, "
            "and coherent compared to the reference (golden) output, given the "
            "original resource description as context."
        ),
        evaluation_steps=[
            "Read the resource description to understand what metadata should be present.",
            "Compare the candidate and reference outputs field by field.",
            "Check accuracy: does the candidate avoid hallucinations (fabricated data)?",
            "Check completeness: does the candidate capture all fields present in the reference?",
            "Check coherence: is the candidate logically consistent and well-structured?",
            "Assign an overall score from 0.0 (completely wrong/missing) to 1.0 (perfect match).",
        ],
        model=gpt_model,
        threshold=0.5,
    )

    test_case = LLMTestCase(
        input=resource_json,
        actual_output=actual_json,
        expected_output=expected_json,
    )

    score = metric.measure(test_case)
    reason = getattr(metric, "reason", "") or ""
    return score, reason


# ── Per-field scorer via raw LLM call ────────────────────────────────────────


def _score_per_field_raw(
    *,
    judge_client: LLMClient,
    actual_json: str,
    expected_json: str,
    resource_json: str,
) -> tuple[float, dict[str, float], str]:
    """Score each field via a raw LLM-as-judge prompt.

    Returns (overall_score, field_scores, notes). Falls back to a structural
    comparison if the LLM call or JSON parsing fails.
    """
    system = (
        "You are a precise metadata quality evaluator. "
        "Return ONLY valid JSON, no explanation, no markdown fences."
    )

    prompt = _SCORING_PROMPT.format(
        resource_description=resource_json,
        expected_output=expected_json,
        actual_output=actual_json,
    )

    response = judge_client.complete_raw(prompt, system_prompt=system)

    # Try to extract JSON from response (handle markdown fence wrapping)
    json_str = response.strip()
    if json_str.startswith("```"):
        lines = json_str.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        json_str = "\n".join(lines).strip()

    try:
        parsed = json.loads(json_str)
        overall = float(parsed.get("overall", 0.0))
        fields_raw = parsed.get("fields", {})
        field_scores: dict[str, float] = {
            str(k): float(v) for k, v in fields_raw.items() if isinstance(v, (int, float))
        }
        notes = str(parsed.get("notes", ""))[:500]
        return overall, field_scores, notes
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning(
            "Failed to parse per-field judge response as JSON: %s. Response: %.200s",
            exc,
            response,
        )
        # Fallback: simple structural field overlap
        try:
            actual_obj = json.loads(actual_json)
            expected_obj = json.loads(expected_json)
            all_fields = set(actual_obj.keys()) | set(expected_obj.keys())
            common = set(actual_obj.keys()) & set(expected_obj.keys())
            only_actual = set(actual_obj.keys()) - set(expected_obj.keys())

            field_scores = {}
            for f in all_fields:
                if f in common:
                    field_scores[f] = 0.5  # present in both, can't judge quality
                elif f in only_actual:
                    field_scores[f] = 0.3  # extra field (candidate has it, ref does not)
                else:
                    field_scores[f] = 0.0  # missing field (ref has it, candidate does not)

            overall = sum(field_scores.values()) / max(len(field_scores), 1)
            notes = "⚠ Per-field scoring fell back to structural comparison (LLM response could not be parsed)."
            return overall, field_scores, notes
        except (json.JSONDecodeError, TypeError):
            return 0.0, {}, f"Per-field scoring failed: {exc}"


# ── Report writer ────────────────────────────────────────────────────────────


def _write_report(report: EvalReport, reports_dir: Path) -> Path:
    """Write the evaluation report as Markdown. Returns the report path."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"live_eval_{report.timestamp}.md"

    lines: list[str] = []
    lines.append(f"# Live Evaluation Report — {report.timestamp}")
    lines.append("")
    lines.append(f"**Model (production):** {report.production_model}")
    lines.append(f"**Model (judge):** {report.judge_model}")
    lines.append(f"**Provider:** {report.provider_name}")
    lines.append(f"**Inputs evaluated:** {len(report.results)}")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Mean overall score | {report.mean_score:.3f} |")

    min_r = report.min_result
    max_r = report.max_result
    lines.append(
        f"| Min score | {min_r.overall:.3f} ({min_r.input_stem}) |"
        if min_r else "| Min score | N/A |"
    )
    lines.append(
        f"| Max score | {max_r.overall:.3f} ({max_r.input_stem}) |"
        if max_r else "| Max score | N/A |"
    )
    lines.append(f"| Threshold | {report.threshold} |")
    passed = report.mean_score >= report.threshold
    lines.append(f"| Status | {'✅ PASS' if passed else '❌ FAIL'} |")
    lines.append("")

    lines.append("## Per-input results")
    lines.append("")

    for r in report.results:
        lines.append(f"### {r.input_stem}")
        lines.append("")
        lines.append(f"- **Overall:** {r.overall:.3f}")
        if r.deepeval_score is not None:
            lines.append(f"- **DeepEval overall:** {r.deepeval_score:.3f}")
        if r.deepeval_reason:
            lines.append(f"- **DeepEval reason:** {r.deepeval_reason[:300]}")
        lines.append("- **Per-field:**")
        if r.field_scores:
            lines.append("  | Field | Score |")
            lines.append("  |-------|-------|")
            for field_name, score in sorted(r.field_scores.items()):
                lines.append(f"  | {field_name} | {score:.2f} |")
        else:
            lines.append("  *(no per-field scores available)*")
        lines.append("")
        if r.notes:
            lines.append(f"**Notes:** {r.notes}")
        else:
            lines.append("**Notes:** —")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Reproduction section
    lines.append("## Reproduction")
    lines.append("")
    lines.append("```")
    lines.append(
        f"uv run python scripts/run_live_eval.py --config {report.config_path} "
        f"--inputs {report.inputs_dir}"
    )
    lines.append("```")
    lines.append("")

    content = "\n".join(lines)
    report_path.write_text(content, encoding="utf-8")
    return report_path


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # 1. Load config
    config_path = Path(args.config).resolve()
    logger.info("Loading config from %s", config_path)
    try:
        config = load_config(config_path)
    except Exception as exc:
        logger.error("Failed to load config: %s", exc)
        sys.exit(1)

    # 2. Check API key
    default_provider = _find_default_provider(config)
    _check_api_key(default_provider)
    api_key = os.environ[default_provider.api_key_env]
    logger.info("Default provider: %s (env: %s)", default_provider.name, default_provider.api_key_env)

    # 3. Validate paths
    inputs_dir = Path(args.inputs)
    expected_dir = Path(args.expected)
    reports_dir = Path(args.reports_dir)

    if not inputs_dir.is_dir():
        logger.error("Inputs directory not found: %s", inputs_dir)
        sys.exit(1)

    expected_files = sorted(expected_dir.glob("*.json")) if expected_dir.is_dir() else []
    if not expected_files:
        print(
            "ERROR: No expected output files found in '%s'.\n"
            "       Run 'make record-golden' first to populate expected outputs."
            % expected_dir,
            file=sys.stderr,
        )
        sys.exit(2)

    input_files = sorted(inputs_dir.glob("*.json"))
    if not input_files:
        logger.error("No .json files found in %s", inputs_dir)
        sys.exit(1)
    logger.info("Found %d input file(s) in %s", len(input_files), inputs_dir)

    # 4. Schema + writer
    schema_registry = get_registry()
    schema: Schema = schema_registry.get(args.schema)
    logger.info("Using schema: %s v%s", schema.name, schema.version)
    writer = OutputWriter(schema)

    # 5. Determine production model from config (first agent's model, or "unknown")
    production_model = config.agents[0].model if config.agents[0].model else "unknown"
    logger.info("Production model: %s", production_model)
    logger.info("Judge model: %s", args.model)

    # 6. Build judge LLM client (fresh, no cache)
    judge_client = create_llm_client(
        default_provider,
        model=args.model,
        temperature=0.0,
        max_tokens=4096,
        use_cache=False,
        use_retry=True,
    )

    # 7. Process each input
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results: list[ScoredResult] = []
    total = len(input_files)
    evaluated = 0

    for input_file in input_files:
        stem = input_file.stem
        logger.info("Processing: %s", input_file.name)

        expected_file = expected_dir / f"{stem}.json"
        if not expected_file.exists():
            logger.warning("  No expected output for %s — skipping", stem)
            continue

        # Load expected output
        try:
            expected_json = expected_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("  Failed to read expected for %s: %s", stem, exc)
            continue

        # Run Pipeline with fresh API calls (temp cache dir)
        try:
            with tempfile.TemporaryDirectory(prefix="metagen_live_eval_") as tmpdir:
                cache_dir = Path(tmpdir) / "cache"
                cache_dir.mkdir(parents=True, exist_ok=True)

                reset_client_cache()
                llm_factory = _make_factory(cache_dir)

                pipeline = Pipeline(config=config, llm_factory=llm_factory)
                pipeline_results: list[PipelineResult] = pipeline.run(
                    FilesystemInputSource(), pattern=str(input_file)
                )

                if not pipeline_results:
                    logger.warning("  No pipeline results for %s", stem)
                    continue

                result = pipeline_results[0]
                if not result.success or result.document is None:
                    logger.error(
                        "  Pipeline FAILED for %s: %s",
                        stem,
                        result.error or "unknown error",
                    )
                    continue

                actual_json = writer.format_json(result.document)
        except Exception as exc:
            logger.error("  Pipeline exception for %s: %s", stem, exc, exc_info=args.verbose)
            continue

        # Load resource description for judge context
        try:
            resource_data = json.loads(input_file.read_text(encoding="utf-8"))
            resource_json = json.dumps(resource_data, indent=2)
        except Exception:
            resource_json = "{}"

        # Score: DeepEval for overall
        deepeval_score: float | None = None
        deepeval_reason: str | None = None
        try:
            deepeval_score, deepeval_reason = _score_overall_deepeval(
                actual_json=actual_json,
                expected_json=expected_json,
                resource_json=resource_json,
                judge_model=args.model,
                api_key=api_key,
                base_url=default_provider.base_url,
            )
            logger.info("  DeepEval overall score: %.3f", deepeval_score)
        except Exception as exc:
            logger.warning("  DeepEval scoring failed: %s — using per-field overall only", exc)

        # Score: Per-field via raw LLM call
        try:
            field_overall, field_scores, notes = _score_per_field_raw(
                judge_client=judge_client,
                actual_json=actual_json,
                expected_json=expected_json,
                resource_json=resource_json,
            )
        except Exception as exc:
            logger.warning("  Per-field scoring failed: %s", exc)
            field_overall = 0.0
            field_scores = {}
            notes = f"Per-field scoring error: {exc}"

        # Primary overall: prefer DeepEval, fall back to field_overall
        overall = deepeval_score if deepeval_score is not None else field_overall

        scored = ScoredResult(
            input_stem=stem,
            overall=overall,
            field_scores=field_scores,
            notes=notes,
            deepeval_score=deepeval_score,
            deepeval_reason=deepeval_reason,
        )
        results.append(scored)
        evaluated += 1

    # 8. Build report
    report = EvalReport(
        timestamp=timestamp,
        production_model=production_model,
        judge_model=args.model,
        provider_name=default_provider.name,
        config_path=str(config_path),
        inputs_dir=str(inputs_dir),
        threshold=args.threshold,
        results=results,
    )
    report_path = _write_report(report, reports_dir)

    # 9. Summary to stderr
    if evaluated == 0:
        print("No inputs were successfully evaluated.", file=sys.stderr)
        sys.exit(1)

    mean_s = report.mean_score
    print(
        f"\nEvaluated {evaluated}/{total} inputs. Mean score: {mean_s:.3f}. "
        f"Report: {report_path}",
        file=sys.stderr,
    )

    if mean_s >= args.threshold:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
