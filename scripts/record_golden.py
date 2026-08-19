#!/usr/bin/env python3
"""Record golden expected outputs and cache snapshot for regression testing.

Runs the gema Pipeline against all input files in the golden inputs directory,
with pinned model+seed+temperature, and saves the outputs + cache bundle.

Prerequisites:
    Set the API key env var referenced by the default provider in your config.
    Example: ``export ZAI_API_KEY=...`` (or OPENAI_API_KEY, OPENCODE_API_KEY, etc.)

Usage:
    uv run python scripts/record_golden.py
    uv run python scripts/record_golden.py --config config/agents.yaml --verbose
    uv run python scripts/record_golden.py -i tests/fixtures/golden/inputs -e tests/fixtures/golden/expected

Output:
    Writes one ``<input_stem>.json`` per input to ``expected/`` and populates
    the diskcache snapshot in ``cache/``.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from datetime import timedelta
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

# The recorded cache is committed to git and replayed indefinitely by
# test_regression.py — it must not expire on CacheManager's normal 7-day TTL,
# or the "no API key needed" regression suite silently falls through to live
# HTTP calls the next time someone runs it.
_GOLDEN_CACHE_TTL = timedelta(days=3650)


def _make_factory(cache_dir: Path) -> LLMClientFactory:
    """Create an LLMClientFactory that uses *cache_dir* for all clients."""

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
            cache_ttl=_GOLDEN_CACHE_TTL,
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
        description="Record golden expected outputs and cache snapshot for regression testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 = some inputs recorded, 1 = all failed, 2 = env not configured.",
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
        help="Directory to write expected outputs (default: tests/fixtures/golden/expected)",
    )
    parser.add_argument(
        "--cache-dir",
        default="tests/fixtures/golden/cache",
        help="Directory for diskcache snapshot (default: tests/fixtures/golden/cache)",
    )
    parser.add_argument(
        "-s", "--schema",
        default="datacite-4.6",
        help="Schema name to use (default: datacite-4.6)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    config_path = Path(args.config).resolve()
    logger.info("Loading config from %s", config_path)
    try:
        config = load_config(config_path)
    except Exception as exc:
        logger.error("Failed to load config: %s", exc)
        sys.exit(1)

    default_provider = _find_default_provider(config)
    _check_api_key(default_provider)
    logger.info("Default provider: %s (env: %s)", default_provider.name, default_provider.api_key_env)

    inputs_dir = Path(args.inputs)
    expected_dir = Path(args.expected)
    cache_dir = Path(args.cache_dir)

    if not inputs_dir.is_dir():
        logger.error("Inputs directory not found: %s", inputs_dir)
        sys.exit(1)

    expected_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Expected outputs directory: %s", expected_dir)

    # Clear and recreate cache directory so the snapshot reflects only this run.
    logger.info("Clearing cache directory: %s", cache_dir)
    shutil.rmtree(cache_dir, ignore_errors=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    schema_registry = get_registry()
    schema: Schema = schema_registry.get(args.schema)
    logger.info("Using schema: %s v%s", schema.name, schema.version)

    writer = OutputWriter(schema)

    input_files = sorted(inputs_dir.glob("*.json"))
    if not input_files:
        logger.error("No .json files found in %s", inputs_dir)
        sys.exit(1)
    logger.info("Found %d input file(s) in %s", len(input_files), inputs_dir)

    llm_factory = _make_factory(cache_dir)
    recorded = 0
    failed = 0
    total = len(input_files)

    for input_file in input_files:
        logger.info("Processing: %s", input_file.name)
        try:
            # Fresh clients per input so cache_dir is injected correctly.
            reset_client_cache()

            # max_workers=1: some providers (observed with ZAI's zai-coding-plan)
            # rate-limit far below what 5 agents firing concurrently need —
            # recording must stay serialized even though the real pipeline
            # defaults to parallel waves.
            pipeline = Pipeline(config=config, llm_factory=llm_factory, max_workers=1)
            results: list[PipelineResult] = pipeline.run(
                FilesystemInputSource(), pattern=str(input_file)
            )

            if not results:
                logger.warning("No results for %s (no matching sources?)", input_file.name)
                failed += 1
                continue

            input_failed = False
            for result in results:
                if result.success and result.document is not None:
                    json_str = writer.format_json(result.document)
                    output_path = expected_dir / f"{input_file.stem}.json"
                    output_path.write_text(json_str, encoding="utf-8")
                    logger.info("  -> wrote %s", output_path)
                    recorded += 1
                else:
                    logger.error(
                        "  !! %s FAILED: %s",
                        input_file.name,
                        result.error or "unknown error",
                    )
                    input_failed = True

            if input_failed:
                failed += 1

        except Exception as exc:
            logger.error("Failed processing %s: %s", input_file.name, exc, exc_info=args.verbose)
            failed += 1

    print(f"\nRecorded {recorded}/{total} outputs to {expected_dir}")
    if failed:
        print(f"  ({failed} input(s) failed — see logs above)", file=sys.stderr)

    if recorded == 0:
        logger.error("All inputs failed.")
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
