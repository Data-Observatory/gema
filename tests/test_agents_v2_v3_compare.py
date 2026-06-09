"""
Config validation and live comparison: andrea_v2 (GLM-5/zai) vs andrea_v3 (deepseek-v4-flash/opencode).

Unit tests always run.
Live comparison requires API keys — skip otherwise.
Run live: pytest tests/test_andrea_compare.py -m live -s
"""

import json
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agents.registry import AgentRegistry
from merger import MetadataMerger
from orchestrator import Orchestrator
from schemas.input_schema import DatasetInput
from schemas.settings_schema import AppSettings, ContextStrategy, LLMSettings

CONFIG_V2 = "config/andrea_v2.json"
CONFIG_V3 = "config/andrea_v3.json"
SAMPLE_INPUT = "examples/sample_input01.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _field_completeness(attrs: dict[str, Any]) -> dict[str, Any]:
    """Return per-field fill rate: count non-empty values recursively."""
    results = {}
    for key, val in attrs.items():
        if isinstance(val, list):
            results[key] = len(val)
        elif isinstance(val, dict):
            filled = sum(1 for v in val.values() if v not in ("", None, [], {}))
            results[key] = filled
        else:
            results[key] = 0 if val in ("", None) else 1
    return results


def _run_pipeline(config_path: str, input_data: DatasetInput) -> tuple[dict, float, dict]:
    """Run full pipeline; return (merged_attrs, elapsed_s, token_usage)."""
    settings = AppSettings(
        llm=LLMSettings(),
        context_strategy=ContextStrategy.ACCUMULATIVE,
    )
    registry = AgentRegistry(config_path, cache_enabled=False)
    orch = Orchestrator(registry, settings)

    t0 = time.perf_counter()
    outputs = orch.run(input_data)
    elapsed = time.perf_counter() - t0

    merger = MetadataMerger()
    result = merger.merge(outputs, input_data=input_data.model_dump())
    token_usage = orch.get_lm_usage()
    return result["attributes"], elapsed, token_usage


# ---------------------------------------------------------------------------
# Unit: config structure validation
# ---------------------------------------------------------------------------


class TestConfigParity:
    """v2 and v3 must have same agents/prompts — only model/provider differs."""

    def test_same_agent_count(self):
        v2 = _load_config(CONFIG_V2)
        v3 = _load_config(CONFIG_V3)
        assert len(v2["agents"]) == len(v3["agents"])

    def test_same_agent_ids(self):
        v2 = _load_config(CONFIG_V2)
        v3 = _load_config(CONFIG_V3)
        ids_v2 = {a["id"] for a in v2["agents"]}
        ids_v3 = {a["id"] for a in v3["agents"]}
        assert ids_v2 == ids_v3

    def test_same_dependencies(self):
        v2 = _load_config(CONFIG_V2)
        v3 = _load_config(CONFIG_V3)
        deps_v2 = {a["id"]: sorted(a.get("depends_on", [])) for a in v2["agents"]}
        deps_v3 = {a["id"]: sorted(a.get("depends_on", [])) for a in v3["agents"]}
        assert deps_v2 == deps_v3

    def test_same_output_fields(self):
        v2 = _load_config(CONFIG_V2)
        v3 = _load_config(CONFIG_V3)
        fields_v2 = {a["id"]: sorted(a["output_fields"]) for a in v2["agents"]}
        fields_v3 = {a["id"]: sorted(a["output_fields"]) for a in v3["agents"]}
        assert fields_v2 == fields_v3

    def test_same_prompts(self):
        v2 = _load_config(CONFIG_V2)
        v3 = _load_config(CONFIG_V3)
        prompts_v2 = {a["id"]: a["prompt_template"] for a in v2["agents"]}
        prompts_v3 = {a["id"]: a["prompt_template"] for a in v3["agents"]}
        assert prompts_v2 == prompts_v3

    def test_v3_model_is_deepseek_flash(self):
        v3 = _load_config(CONFIG_V3)
        for agent in v3["agents"]:
            assert agent["llm_config"]["model"] == "deepseek-v4-flash", (
                f"Agent '{agent['id']}' has wrong model: {agent['llm_config']['model']}"
            )

    def test_v3_provider_is_opencode(self):
        v3 = _load_config(CONFIG_V3)
        for agent in v3["agents"]:
            assert agent["llm_config"]["provider"] == "opencode", (
                f"Agent '{agent['id']}' has wrong provider: {agent['llm_config']['provider']}"
            )

    def test_v2_provider_is_zai(self):
        v2 = _load_config(CONFIG_V2)
        for agent in v2["agents"]:
            assert agent["llm_config"]["provider"] == "zai-coding-plan"

    def test_v3_config_loadable_by_registry(self):
        """Registry must parse v3 without raising (dependency check included)."""
        registry = AgentRegistry(CONFIG_V3)
        order = registry.get_execution_order()
        assert len(order) > 0

    def test_v2_config_loadable_by_registry(self):
        registry = AgentRegistry(CONFIG_V2)
        order = registry.get_execution_order()
        assert len(order) > 0


# ---------------------------------------------------------------------------
# Live comparison: requires ZAI_API_KEY + OPENCODE_API_KEY
# ---------------------------------------------------------------------------

_has_v2_key = bool(os.environ.get("ZAI_API_KEY"))
_has_v3_key = bool(os.environ.get("OPENCODE_API_KEY"))
_skip_live = pytest.mark.skipif(
    not (_has_v2_key and _has_v3_key),
    reason="ZAI_API_KEY and OPENCODE_API_KEY required for live comparison",
)


@pytest.mark.live
@_skip_live
class TestLiveComparison:
    """Run both configs against sample_input01 and compare output quality."""

    @pytest.fixture(scope="class")
    def pipeline_results(self):
        with open(SAMPLE_INPUT, encoding="utf-8") as f:
            input_data = DatasetInput(**json.load(f))

        attrs_v2, elapsed_v2, tokens_v2 = _run_pipeline(CONFIG_V2, input_data)
        attrs_v3, elapsed_v3, tokens_v3 = _run_pipeline(CONFIG_V3, input_data)

        return {
            "v2": {"attrs": attrs_v2, "elapsed": elapsed_v2, "tokens": tokens_v2},
            "v3": {"attrs": attrs_v3, "elapsed": elapsed_v3, "tokens": tokens_v3},
        }

    def test_both_produce_titles(self, pipeline_results):
        assert len(pipeline_results["v2"]["attrs"].get("titles", [])) > 0
        assert len(pipeline_results["v3"]["attrs"].get("titles", [])) > 0

    def test_both_produce_descriptions(self, pipeline_results):
        assert len(pipeline_results["v2"]["attrs"].get("descriptions", [])) > 0
        assert len(pipeline_results["v3"]["attrs"].get("descriptions", [])) > 0

    def test_both_produce_creators(self, pipeline_results):
        assert len(pipeline_results["v2"]["attrs"].get("creators", [])) > 0
        assert len(pipeline_results["v3"]["attrs"].get("creators", [])) > 0

    def test_both_produce_rights(self, pipeline_results):
        assert len(pipeline_results["v2"]["attrs"].get("rights", [])) > 0
        assert len(pipeline_results["v3"]["attrs"].get("rights", [])) > 0

    def test_completeness_report(self, pipeline_results, capsys):
        """Print side-by-side completeness. Never fails — informational only."""
        v2_fill = _field_completeness(pipeline_results["v2"]["attrs"])
        v3_fill = _field_completeness(pipeline_results["v3"]["attrs"])
        all_keys = sorted(set(v2_fill) | set(v3_fill))

        lines = [
            "\n" + "=" * 60,
            f"{'FIELD':<28} {'V2 (GLM-5)':>12} {'V3 (DS-Flash)':>13}",
            "-" * 60,
        ]
        for key in all_keys:
            v2_val = v2_fill.get(key, 0)
            v3_val = v3_fill.get(key, 0)
            marker = " <" if v3_val > v2_val else ("  " if v3_val == v2_val else " >")
            lines.append(f"{key:<28} {str(v2_val):>12} {str(v3_val):>13}{marker}")

        lines += [
            "-" * 60,
            f"Elapsed v2: {pipeline_results['v2']['elapsed']:.1f}s",
            f"Elapsed v3: {pipeline_results['v3']['elapsed']:.1f}s",
            "=" * 60,
        ]

        # Print token usage per model
        for ver, label in [("v2", "V2 tokens"), ("v3", "V3 tokens")]:
            for model, stats in pipeline_results[ver]["tokens"].items():
                lines.append(f"{label} [{model}]: {stats.get('total_tokens', 0):,}")

        with capsys.disabled():
            print("\n".join(lines))

    def test_v3_no_missing_required_fields(self, pipeline_results):
        """v3 must not regress on fields v2 filled."""
        required = ["titles", "descriptions", "creators", "publishers"]
        v2 = pipeline_results["v2"]["attrs"]
        v3 = pipeline_results["v3"]["attrs"]
        regressions = []
        for field in required:
            v2_count = len(v2.get(field, []))
            v3_count = len(v3.get(field, []))
            if v2_count > 0 and v3_count == 0:
                regressions.append(f"{field}: v2={v2_count} v3={v3_count}")
        assert not regressions, f"v3 regressions: {regressions}"
