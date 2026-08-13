"""Shared, corpus-agnostic evaluation infrastructure for dev scripts.

Two concerns live here, both reused across every eval script regardless of
which corpus (Geoportal, do_catalog, golden fixtures, ...) is being scored:

1. Running the pipeline for an arbitrary provider:model spec, with the
   MODEL_EXTRA_BODY override table for known provider/model quirks.
2. Scoring an actual output against a ground truth — either structurally
   (Jaccard/exact-match on extracted fields) or semantically (LLM-as-judge
   via DeepEval GEval + a hand-rolled per-field judge).

Nothing here assumes a fixed input/ground-truth directory, a specific
ground-truth JSON shape, or a specific corpus name — callers pass paths and
already-unwrapped/adapted dicts.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from metadata_enricher.config.models import ProviderConfig

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/agents.yaml")
SCHEMA_NAME = "datacite-4.6"

DEFAULT_PROVIDER = "zai-coding-plan"

# Model/provider-specific request-body overrides needed to make structured
# output work at all. Several models default to a "thinking mode" via
# OpenCode's Console Go routing, which rejects Instructor's forced
# tool_choice with a 400 — confirmed upstream bug for DeepSeek V4
# (opencode #24114) and independently reproduced for qwen3.7-plus this
# session. Disabling thinking mode is the documented workaround; it costs
# the model's extended-reasoning quality. Only added here once reproduced —
# never assumed by analogy (e.g. mimo-v2.5 needs no override at all).
MODEL_EXTRA_BODY: dict[tuple[str, str], dict[str, Any]] = {
    ("opencode", "deepseek-v4-flash"): {"thinking": {"type": "disabled"}},
    ("opencode", "deepseek-v4-pro"): {"thinking": {"type": "disabled"}},
    ("opencode", "qwen3.7-plus"): {"thinking": {"type": "disabled"}},
}

# Weights for the structural "overall" score (must sum to 1.0)
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
# Model spec parsing — "provider:model" or bare "model" (defaults to zai)
# ---------------------------------------------------------------------------

def parse_model_spec(spec: str) -> tuple[str, str]:
    """"provider:model" -> (provider, model). Bare "model" defaults to
    DEFAULT_PROVIDER, preserving the original bare-GLM-name sweep syntax."""
    if ":" in spec:
        provider, model = spec.split(":", 1)
        return provider.strip(), model.strip()
    return DEFAULT_PROVIDER, spec.strip()


def sanitize_label(spec: str) -> str:
    """Filesystem/dict-key-safe label for a model spec (dirs, cache keys)."""
    return spec.replace(".", "_").replace(":", "__").replace("/", "_")


def resolve_max_workers(provider: str, model: str, config_path: Path = CONFIG_PATH) -> int:
    """PipelineConfig.effective_max_workers for *provider*/*model*, without
    building a full Pipeline. Callers deciding whether/how much to
    parallelize (e.g. cross-item concurrency in
    compare_models.py/judge_models.py) read this instead of hardcoding a
    provider or model name — the global/provider/model override cascade
    lives in config/providers.yaml, this is just the lookup."""
    from metadata_enricher.config.loader import load_config

    return load_config(config_path).effective_max_workers(provider, model)


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------

def run_pipeline_for_model(
    input_path: Path,
    provider: str,
    model: str,
    output_root: Path,
    *,
    enrich: bool = False,
    max_attempts: int = 3,
    cache_label: str | None = None,
    config_path: Path = CONFIG_PATH,
    schema_name: str = SCHEMA_NAME,
) -> dict[str, Any] | None:
    """Run pipeline on a single input with the specified provider + model.

    Retries up to *max_attempts* times. Between retries, does NOT reset the
    LLM client cache, so previously-successful agents are served from cache
    (instant) and only failed agents (no cache entry) get re-called. This
    handles reasoning-model flakiness where reasoning budget exhaustion
    causes empty content → Instructor parse failure.

    Returns the output with the highest field coverage across all attempts,
    or None if every attempt failed.
    """
    # Lazy imports — avoid heavy startup if just generating a report
    from metadata_enricher.agents.registry import LLMClientFactory
    from metadata_enricher.config.loader import load_config
    from metadata_enricher.input_sources.filesystem import FilesystemInputSource
    from metadata_enricher.llm.base import LLMClient
    from metadata_enricher.llm.factory import create_llm_client
    from metadata_enricher.output import OutputWriter
    from metadata_enricher.pipeline import Pipeline
    from metadata_enricher.schemas import get_registry

    config = load_config(config_path)

    if enrich:
        config.enable_identifier_enrichment = True

    # Override all agents to use the target provider + model
    extra_body = MODEL_EXTRA_BODY.get((provider, model))
    for agent in config.agents:
        agent.model = model
        agent.provider = provider
        agent.extra_body = extra_body

    # Per-model cache directory
    cache_dir = output_root / "cache" / (cache_label or sanitize_label(model))
    cache_dir.mkdir(parents=True, exist_ok=True)

    def llm_factory(provider: ProviderConfig, model: str, **kwargs: Any) -> LLMClient:
        return create_llm_client(provider, model, cache_dir=cache_dir, **kwargs)

    # BUG FIXED: this call previously passed no max_workers at all, so it
    # silently used Pipeline's own constructor default (4) regardless of
    # config.max_workers (1, tuned for zai-coding-plan's tight rate limit —
    # see config/agents.yaml). Every eval run against zai-coding-plan this
    # session ran at unintended concurrency=4, not the intended 1. Resolve
    # per-provider via PipelineConfig.effective_max_workers (global default,
    # overridable per-provider in config/providers.yaml) — the same
    # resolution path production's cli.py uses, no hardcoded provider name
    # anywhere in this file.
    pipeline = Pipeline(
        config=config,
        llm_factory=cast("LLMClientFactory", llm_factory),
        max_workers=config.effective_max_workers(provider, model),
    )
    source = FilesystemInputSource()

    schema = get_registry().get(schema_name)
    writer = OutputWriter(schema=schema)

    best_output: dict[str, Any] | None = None
    best_field_count = 0

    for _attempt in range(1, max_attempts + 1):
        results = pipeline.run(source, pattern=str(input_path))

        if not results or not results[0].success or results[0].document is None:
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
    """Case-fold and strip diacritics (NFKD, drop combining marks) so
    "Educación" and "Educacion" compare equal. Verified (2026-08-13) to move
    nothing on the current do_catalog corpus -- no ground-truth/output name
    pair there differs only by accent -- kept as correctness hardening for
    corpora where that isn't true."""
    folded = unicodedata.normalize("NFKD", s.strip().lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


def extract_creator_names(attrs: dict[str, Any]) -> set[str]:
    return {
        _norm(c["creator_name"])
        for c in attrs.get("creators", [])
        if c.get("creator_name", "").strip()
    }


def extract_ror_ids(attrs: dict[str, Any]) -> set[str]:
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


def extract_subjects(attrs: dict[str, Any]) -> set[str]:
    return {
        _norm(s["subject_name"])
        for s in attrs.get("subjects", [])
        if s.get("subject_name", "").strip()
    }


def extract_categories(attrs: dict[str, Any]) -> set[str]:
    return {
        f"{_norm(c.get('name', ''))}|{_norm(c.get('sub_category', ''))}"
        for c in attrs.get("categories", [])
        if c.get("name", "").strip()
    }


def extract_rights_id(attrs: dict[str, Any]) -> str:
    rights = attrs.get("rights", [])
    if rights and isinstance(rights, list):
        return _norm(rights[0].get("rights_identifier", ""))
    return ""


def extract_languages(attrs: dict[str, Any]) -> set[str]:
    return {
        _norm(lang["lang_code"])
        for lang in attrs.get("languages", [])
        if lang.get("lang_code", "").strip()
    }


def extract_geo_places(attrs: dict[str, Any]) -> set[str]:
    """Handle both flat geo_locations (current schema, and do_catalog ground
    truth) and legacy nested temporal_geo.geo_locations."""
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


def extract_media_formats(attrs: dict[str, Any]) -> set[str]:
    return {
        _norm(m["format"])
        for m in attrs.get("media_files", [])
        if m.get("format", "").strip()
    }


def extract_populated_fields(attrs: dict[str, Any]) -> set[str]:
    return {
        k for k, v in attrs.items()
        if v is not None and v != [] and v != {}
    }


# ---------------------------------------------------------------------------
# Structural (Jaccard-vs-truth) scoring
# ---------------------------------------------------------------------------

def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def compare_outputs(truth: dict[str, Any], actual: dict[str, Any]) -> dict[str, float]:
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

    # Empty-vs-empty must score 1.0 like every other metric's jaccard() --
    # the old `and extract_rights_id(truth)` guard forced 0.0 whenever truth
    # had no rights_identifier, even if actual matched it exactly (i.e. both
    # empty). Verified (2026-08-13): only 1/100 do_catalog ground-truth items
    # actually hit this case -- the remaining ~0.099 gap in this metric is a
    # real model/prompt recall gap (99/100 truth items carry a real SPDX id,
    # models almost never emit one), not a scoring bug -- see BACKLOG.md.
    scores["rights"] = 1.0 if extract_rights_id(truth) == extract_rights_id(actual) else 0.0

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
# LLM-as-judge scoring (DeepEval GEval + hand-rolled per-field judge)
# ---------------------------------------------------------------------------

SCORING_PROMPT = """\
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


def score_overall_deepeval(
    *,
    actual_json: str,
    expected_json: str,
    resource_json: str,
    judge_model: str,
    api_key: str,
    base_url: str | None,
    generation_kwargs: dict[str, Any] | None = None,
) -> tuple[float, str]:
    """Score overall semantic quality using DeepEval GEval.

    Returns (score, reason). Raises on failure (treated as non-fatal upstream
    by most callers — but judge_models.py must NOT swallow this silently
    into a different scorer; see its own hard-fail-on-inconsistency handling).

    *generation_kwargs* is forwarded to GPTModel — needed for provider/model
    request-body overrides on the judge model itself (mirrors MODEL_EXTRA_BODY
    above). Additive: omitted, this behaves exactly as before it existed.
    """
    from deepeval.metrics import GEval  # noqa: PLC0415 — optional dep
    from deepeval.models import GPTModel  # noqa: PLC0415
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams  # noqa: PLC0415

    gpt_model = GPTModel(
        model=judge_model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        generation_kwargs=generation_kwargs,
    )

    metric = GEval(
        name="DataCite Semantic Quality",
        # Required since deepeval made evaluation_params mandatory — must list
        # every LLMTestCase field this metric actually reads (input/actual_output/
        # expected_output), or GEval raises "requires evaluation_params" at
        # measure() time instead of at construction.
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
        ],
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


def score_per_field_raw(
    *,
    judge_client: Any,
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

    prompt = SCORING_PROMPT.format(
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
