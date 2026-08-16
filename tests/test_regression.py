"""Regression tests — cache-replay semantic similarity vs golden outputs.

Uses ``json-semantic-diff`` (STED algorithm) for structural-semantic JSON comparison.
Cache replay avoids real API calls — no API key needed when golden fixtures are populated.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import json_semantic_diff
import pytest

from metadata_enricher.agents.registry import LLMClientFactory
from metadata_enricher.config.loader import load_config
from metadata_enricher.config.models import PipelineConfig, ProviderConfig
from metadata_enricher.input_sources.filesystem import FilesystemInputSource
from metadata_enricher.llm.base import LLMClient
from metadata_enricher.llm.factory import create_llm_client, reset_client_cache
from metadata_enricher.output import OutputWriter
from metadata_enricher.pipeline import Pipeline, PipelineResult
from metadata_enricher.schemas import get_registry

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "golden"
INPUTS_DIR = FIXTURES_DIR / "inputs"
EXPECTED_DIR = FIXTURES_DIR / "expected"
CACHE_DIR = FIXTURES_DIR / "cache"
CONFIG_PATH = Path("config/agents.yaml")

SIMILARITY_THRESHOLD = 0.85

# ---------------------------------------------------------------------------
# Parameterisation helpers
# ---------------------------------------------------------------------------

_INPUT_FILES = sorted(INPUTS_DIR.glob("*.json")) if INPUTS_DIR.exists() else []
_INPUT_STEMS = [f.stem for f in _INPUT_FILES]

# Only parametrise inputs that have corresponding expected output files.
_PARAM_STEMS = sorted(
    stem
    for stem in _INPUT_STEMS
    if EXPECTED_DIR.exists() and (EXPECTED_DIR / f"{stem}.json").exists()
)

_HAS_FIXTURES = len(_PARAM_STEMS) > 0

# Marker applied to every test in this module.
pytestmark = [pytest.mark.regression]

# ---------------------------------------------------------------------------
# Factory helper (mirrors scripts/record_golden.py:_make_factory)
# ---------------------------------------------------------------------------


def _make_factory(cache_dir: Path) -> LLMClientFactory:
    """Create an LLMClientFactory that uses *cache_dir* for all clients."""

    def _factory(
        provider: ProviderConfig,
        model: str,
        temperature: float,
        max_tokens: int | None,
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


# ---------------------------------------------------------------------------
# Semantic similarity helpers
# ---------------------------------------------------------------------------


def _compute_similarity(actual: dict[str, Any], expected: dict[str, Any]) -> float:
    """Return overall similarity via json_semantic_diff.compare()."""
    result = json_semantic_diff.compare(actual, expected)
    return result.similarity_score


def _per_field_scores(
    actual: dict[str, Any], expected: dict[str, Any]
) -> dict[str, float]:
    """Return per-top-level-key similarity scores.

    Keys present in only one dict score 0.0.  Keys present in both are
    compared via their own ``json_semantic_diff.compare()`` call.
    """
    all_keys = sorted(set(actual.keys()) | set(expected.keys()))
    scores: dict[str, float] = {}
    for key in all_keys:
        if key in actual and key in expected:
            scores[key] = json_semantic_diff.compare(actual[key], expected[key]).similarity_score
        elif key in actual:
            scores[key] = 0.0
        else:
            scores[key] = 0.0
    return scores


def _format_failure_message(
    actual: dict[str, Any],
    expected: dict[str, Any],
    overall: float,
    threshold: float,
    per_field: dict[str, float],
) -> str:
    """Build a rich failure message with per-field breakdown."""
    result = json_semantic_diff.compare(actual, expected)
    missing = [p for p in result.unmatched_right if p.startswith("/") and "/" in p[1:]]
    extra = [p for p in result.unmatched_left if p.startswith("/") and "/" in p[1:]]

    lines = [
        f"Regression detected: similarity={overall:.3f} < threshold={threshold}",
        "",
        "Per-field scores:",
    ]
    for key, score in sorted(per_field.items()):
        lines.append(f"  {key}: {score:.3f}")

    if missing:
        lines.append("")
        lines.append(f"Missing keys (in expected but not actual): {missing}")
    if extra:
        lines.append("")
        lines.append(f"Extra keys (in actual but not expected): {extra}")

    lines.append("")
    lines.append(
        "To regenerate golden outputs, run: make record-golden"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Regression semantics (cache-replay + similarity assertion)
# ---------------------------------------------------------------------------


class TestRegressionSemantics:
    """Pipeline outputs must remain semantically similar to committed golden."""

    @pytest.mark.skipif(
        not _HAS_FIXTURES,
        reason="No golden outputs recorded. Run `make record-golden` first.",
    )
    @pytest.mark.parametrize("input_stem", _PARAM_STEMS)
    def test_output_matches_golden_semantically(self, input_stem: str) -> None:
        """Cache-replay the pipeline and assert similarity >= SIMILARITY_THRESHOLD."""
        # 1. Load expected output from committed golden.
        expected_path = EXPECTED_DIR / f"{input_stem}.json"
        with expected_path.open("r", encoding="utf-8") as f:
            expected: dict[str, Any] = json.load(f)

        # 2. Build Pipeline with cache_dir pointed at the committed snapshot.
        reset_client_cache()
        config: PipelineConfig = load_config(CONFIG_PATH)

        # Override every configured provider's API key with a dummy value to
        # enforce cache-only mode. `uv run` auto-loads .env, so real keys
        # would otherwise leak into test env; CI has no .env and no key at
        # all, so this must not depend on any real key being present either.
        # Using [] assignment (not setdefault) ensures real keys are
        # overridden. Cache HITs intercept before any real API call, so the
        # dummy key is never actually used.
        for provider in config.providers:
            os.environ[provider.api_key_env] = "dummy-regression-cache-only-key"
        # Force off regardless of the real config: this test validates LLM
        # output against a fixed input snapshot via cache replay, not the
        # live content-fetch mechanism (covered separately in
        # test_pipeline_integration.py). Without this, sample_input05 (a
        # real but dead URL with no fetched_content) would trigger a live
        # HTTP request on every regression run, breaking the "no API key/
        # network needed" cache-replay contract.
        config = config.model_copy(update={"enable_content_fetch": False})
        llm_factory = _make_factory(CACHE_DIR)
        pipeline = Pipeline(config=config, llm_factory=llm_factory)

        # 4. Run pipeline on the single input file.
        input_file = INPUTS_DIR / f"{input_stem}.json"
        source = FilesystemInputSource()
        results: list[PipelineResult] = pipeline.run(source, pattern=str(input_file))

        assert len(results) == 1, (
            f"Expected 1 pipeline result for {input_stem}, got {len(results)}"
        )
        result = results[0]
        assert result.success, f"Pipeline failed for {input_stem}: {result.error}"
        assert result.document is not None, f"No document produced for {input_stem}"

        # 5. Format output via OutputWriter and parse as JSON dict.
        schema_registry = get_registry()
        schema = schema_registry.get(config.schema_name)
        writer = OutputWriter(schema)
        json_str = writer.format_json(result.document)
        actual: dict[str, Any] = json.loads(json_str)

        # 6. Compute similarity.
        overall = _compute_similarity(actual, expected)

        # 7. Assert with rich failure message.
        if overall < SIMILARITY_THRESHOLD:
            per_field = _per_field_scores(actual, expected)
            msg = _format_failure_message(
                actual, expected, overall, SIMILARITY_THRESHOLD, per_field
            )
            pytest.fail(msg)


# ---------------------------------------------------------------------------
# Shape checks (always run, even without golden outputs)
# ---------------------------------------------------------------------------


class TestRegressionShape:
    """Quick shape-only checks that don't need golden outputs to be recorded."""

    def test_inputs_dir_has_samples(self) -> None:
        """Inputs dir must have at least one sample to be useful."""
        assert len(_INPUT_STEMS) > 0, (
            f"No .json files found in {INPUTS_DIR}. "
            "This directory is committed and should always have samples."
        )

    @pytest.mark.skipif(
        _HAS_FIXTURES,
        reason="Golden outputs already recorded; expected/ is not empty.",
    )
    def test_expected_dir_is_empty_pre_recording(self) -> None:
        """If expected/ is empty, document that this is the pre-recording state."""
        files = list(EXPECTED_DIR.glob("*.json"))
        assert len(files) == 0, (
            f"Expected no .json files in {EXPECTED_DIR}, but found {len(files)}. "
            "This test should have been skipped — is _HAS_FIXTURES stale?"
        )
