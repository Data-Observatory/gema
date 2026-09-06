#!/usr/bin/env python3
"""A/B diagnostic: CDIF-generation exported to DataCite vs. DataCite-direct
generation (spec §9, ``docs/cdif_pivot_implementation_plan.md``'s "A/B
diagnostic" section).

Question this answers: did retargeting live generation from DataCite 4.6
straight to CDIF Discovery (then crosswalking to DataCite only on export)
lose or corrupt data, compared to the old way of generating DataCite
directly? A regression here would mean ``exporters/datacite.py``'s CDIF ->
DataCite field mapping is missing/misreading something a DataCite-native
agent prompt used to capture correctly.

Side A ("new"): run the *current* pipeline (``config/agents.yaml``,
``schema_name: cdif-discovery``) over the 6 golden inputs, LLM calls
cache-replayed against the same committed cache ``test_regression.py``
replays (zero LLM API cost -- every provider key is overwritten with a
dummy value first, so a cache miss fails loudly instead of reaching a real
LLM endpoint), then crosswalk each resulting CDIF ``MetadataDocument``
through ``exporters.datacite.to_datacite_json`` -- pure, no LLM call.

Verified, and worth being precise about: this is NOT zero-network. Like
``test_regression.py`` itself (checked directly -- neither disables it,
and neither ``identifier_enricher.py`` nor ``doi_resolver.py``/its ROR
-/ISNI/ORCID/DOI.org clients cache their HTTP responses anywhere), a run
still makes a handful of real, small GET requests to public registries
(ROR, ORCID, ISNI, doi.org) for identifier enrichment and DOI resolution --
this script only forces ``enable_content_fetch=False`` and dummy LLM keys,
matching test_regression.py's own guarantee exactly (zero LLM cost), not a
stronger one. A consequence worth knowing: those live lookups are fuzzy-
matched against a real, current registry, so a resource's identifier
-enrichment output (and therefore its DataCite ``creators``/``publishers``
``name_identifiers``) can genuinely vary run-to-run independent of any code
change here -- this script does not (and cannot, without disabling
enrichment and thereby comparing a different, degraded document than the
one actually shipped) eliminate that variance.

Side B ("baseline"): NOT re-run. ``tests/fixtures/golden_datacite46_baseline/``
is a frozen snapshot taken immediately pre-pivot -- its ``expected/*.json``
files already ARE the recorded output of running the old
``config/legacy/agents_datacite46.yaml`` (DataCite-native generation)
end-to-end. Re-running that config would require either re-registering the
deregistered ``datacite-4.6`` schema (a `SchemaRegistry` hack) or a second,
parallel cache-replay path with no added signal -- the frozen JSON already
*is* that side's ground truth, so this script just reads it. See that
directory's own README.md for the snapshot's provenance.

Scoring reuses ``json_semantic_diff`` (the STED algorithm), the same
dependency and threshold ``tests/test_regression.py`` uses, for an
apples-to-apples similarity number.

Read the per-resource scores as informational, not a pass/fail regression
gate: the baseline predates every one of Open Questions #16-#23 (nested/
top-level identifier cardinality, contributor Role wrapper, citation shape
collapsed to a literal string, ``schema:url`` fallback, ...) -- all
deliberate, intentional CDIF-side shape changes made *after* the snapshot
was frozen, for reasons unrelated to the DataCite crosswalk's own
correctness. Expect the overall/per-field numbers to run low today for
that reason alone; that is not evidence of a crosswalk bug by itself. Use
the per-field breakdown to sanity-check that a field didn't silently go
empty/garbled (e.g. ``creators`` still has real names and a plausible
shape), not to chase 1.0 on every field.

Manual-only -- not wired into ci.yml, ``make test``, or ``make
test-regression``. Run via ``make ab-eval`` or directly:

    uv run python scripts/ab_eval_cdif_vs_datacite.py
    uv run python scripts/ab_eval_cdif_vs_datacite.py --threshold 0.90 -v

Exit codes: 0 = every resource at/above threshold, 1 = at least one below.
Given the baseline-staleness caveat above, a non-zero exit is expected and
informational, not necessarily a problem to fix.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import json_semantic_diff

from metadata_enricher.agents.registry import LLMClientFactory
from metadata_enricher.config.loader import load_config
from metadata_enricher.config.models import PipelineConfig, ProviderConfig
from metadata_enricher.exporters.datacite import to_datacite_json
from metadata_enricher.input_sources.filesystem import FilesystemInputSource
from metadata_enricher.llm.base import LLMClient
from metadata_enricher.llm.factory import create_llm_client, reset_client_cache
from metadata_enricher.pipeline import Pipeline, PipelineResult

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

CDIF_CONFIG = REPO_ROOT / "config" / "agents.yaml"
CDIF_INPUTS = REPO_ROOT / "tests" / "fixtures" / "golden" / "inputs"
CDIF_CACHE = REPO_ROOT / "tests" / "fixtures" / "golden" / "cache"

BASELINE_EXPECTED = (
    REPO_ROOT / "tests" / "fixtures" / "golden_datacite46_baseline" / "expected"
)

DEFAULT_THRESHOLD = 0.85  # matches test_regression.py's SIMILARITY_THRESHOLD


def _cache_only_factory(cache_dir: Path) -> LLMClientFactory:
    """Same shape as test_regression.py's/record_golden.py's ``_make_factory``
    -- every client it builds is pinned to *cache_dir*, so a cache HIT
    intercepts before any real request is ever constructed."""

    def _factory(
        provider: ProviderConfig,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        extra_body: dict[str, object] | None = None,
    ) -> LLMClient:
        return create_llm_client(
            provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
            cache_dir=cache_dir,
        )

    return _factory


def _force_cache_only(config: PipelineConfig) -> PipelineConfig:
    """Overwrite every provider's API key with a dummy value and disable
    content-fetch, so an LLM cache miss fails loudly instead of silently
    reaching a real LLM endpoint. Mirrors test_regression.py exactly --
    including what it does NOT cover: identifier enrichment/DOI resolution
    still make real, small GET requests to ROR/ORCID/ISNI/doi.org, same as
    that suite (see this module's docstring)."""
    for provider in config.providers:
        os.environ[provider.api_key_env] = "dummy-ab-eval-cache-only-key"
    return config.model_copy(update={"enable_content_fetch": False})


def _run_cdif_as_datacite(stem: str) -> dict[str, Any]:
    """Cache-replay the current (CDIF) pipeline for *stem*, then crosswalk
    the resulting document to DataCite's native shape. Raises if the
    pipeline doesn't succeed -- a cache miss here means the committed
    ``tests/fixtures/golden/cache`` is stale/incomplete, which is itself
    worth surfacing loudly rather than masking as a similarity mismatch."""
    reset_client_cache()
    config = _force_cache_only(load_config(CDIF_CONFIG))
    pipeline = Pipeline(config=config, llm_factory=_cache_only_factory(CDIF_CACHE))

    input_file = CDIF_INPUTS / f"{stem}.json"
    results: list[PipelineResult] = pipeline.run(
        FilesystemInputSource(), pattern=str(input_file)
    )
    if len(results) != 1:
        raise RuntimeError(f"{stem}: expected 1 pipeline result, got {len(results)}")
    result = results[0]
    if not result.success or result.document is None:
        raise RuntimeError(f"{stem}: CDIF cache-replay failed: {result.error}")

    export = to_datacite_json(result.document)
    if export.warnings:
        logger.warning("%s: to_datacite_json warnings: %s", stem, export.warnings)
    return export.datacite_json


def _load_baseline(stem: str) -> dict[str, Any]:
    path = BASELINE_EXPECTED / f"{stem}.json"
    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def _per_field_scores(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, float]:
    all_keys = sorted(set(actual.keys()) | set(expected.keys()))
    scores: dict[str, float] = {}
    for key in all_keys:
        if key in actual and key in expected:
            scores[key] = json_semantic_diff.compare(actual[key], expected[key]).similarity_score
        else:
            scores[key] = 0.0
    return scores


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "A/B diagnostic: CDIF-generated-then-DataCite-exported vs. "
            "frozen DataCite-direct-generation baseline, cache-replay only."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Similarity threshold below which a resource is flagged (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(message)s",
    )

    stems = sorted(p.stem for p in BASELINE_EXPECTED.glob("*.json"))
    if not stems:
        logger.error("No baseline fixtures found in %s", BASELINE_EXPECTED)
        return 1

    rows: list[tuple[str, float]] = []
    any_failed_to_run = False

    for stem in stems:
        try:
            actual = _run_cdif_as_datacite(stem)
        except Exception as exc:  # noqa: BLE001 - report, keep scoring the rest
            logger.error("%s: could not produce CDIF->DataCite output: %s", stem, exc)
            any_failed_to_run = True
            continue
        expected = _load_baseline(stem)

        overall = json_semantic_diff.compare(actual, expected).similarity_score
        rows.append((stem, overall))

        if overall < args.threshold:
            per_field = _per_field_scores(actual, expected)
            logger.info("%s: overall=%.3f (below threshold %.2f)", stem, overall, args.threshold)
            for key, score in sorted(per_field.items(), key=lambda kv: kv[1]):
                logger.info("    %-24s %.3f", key, score)
        else:
            logger.info("%s: overall=%.3f", stem, overall)

    print()
    print(f"{'resource':<20} {'similarity':>10}  status")
    print("-" * 44)
    below_threshold = 0
    for stem, overall in rows:
        status = "OK" if overall >= args.threshold else "BELOW THRESHOLD"
        if status != "OK":
            below_threshold += 1
        print(f"{stem:<20} {overall:>10.3f}  {status}")
    print("-" * 44)
    print(f"{len(rows)}/{len(stems)} resources compared, {below_threshold} below threshold={args.threshold}")

    if any_failed_to_run or below_threshold:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
