import argparse
import json
import logging
import os
import glob as glob_module
from pathlib import Path
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from schemas.input_schema import DatasetInput
from schemas.settings_schema import AppSettings, ContextStrategy, LLMSettings
from agents.registry import AgentRegistry
from orchestrator import Orchestrator
from merger import MetadataMerger


def parse_args():
    parser = argparse.ArgumentParser(
        description="Enrich dataset metadata using AI agents"
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to input JSON file or directory/glob pattern",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Path to output JSON file or directory (default: output/)",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config/agents.json",
        help="Path to agents config file",
    )
    parser.add_argument(
        "--strategy",
        "-s",
        choices=["accumulative", "layered"],
        default="accumulative",
        help="Context passing strategy",
    )
    return parser.parse_args()


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def resolve_input_files(input_path: str) -> list[Path]:
    input_path_obj = Path(input_path)

    if input_path_obj.is_dir():
        return sorted(input_path_obj.glob("*.json"))
    elif "*" in input_path:
        return sorted([Path(p) for p in glob_module.glob(input_path)])
    elif input_path_obj.exists():
        return [input_path_obj]
    else:
        raise FileNotFoundError(f"Input not found: {input_path}")


def ensure_output_dir(output_path: str | None, is_batch: bool) -> Path:
    if output_path:
        out = Path(output_path)
    else:
        out = Path(__file__).parent / "output"

    if is_batch:
        out.mkdir(parents=True, exist_ok=True)

    return out


def format_token_usage(usage: dict[str, Any]) -> dict[str, Any]:
    formatted: dict[str, Any] = {
        "by_model": {},
        "by_agent": {},
        "total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    for model, stats in usage.get("by_model", {}).items():
        prompt = stats.get("prompt_tokens", 0)
        completion = stats.get("completion_tokens", 0)
        total = stats.get("total_tokens", prompt + completion)

        formatted["by_model"][model] = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        }
        formatted["total"]["prompt_tokens"] += prompt
        formatted["total"]["completion_tokens"] += completion
        formatted["total"]["total_tokens"] += total

    for agent_id, stats in usage.get("by_agent", {}).items():
        formatted["by_agent"][agent_id] = {
            "model": stats.get("model", "unknown"),
            "prompt_tokens": stats.get("prompt_tokens", 0),
            "completion_tokens": stats.get("completion_tokens", 0),
            "total_tokens": stats.get("total_tokens", 0),
        }

    return formatted


def fetch_url_content(url: str, timeout: int = 30) -> str:
    """Fetch HTML content from a URL for agent context."""
    import requests

    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; metadata-enricher/1.0)"},
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logging.getLogger(__name__).warning(f"Failed to fetch {url}: {e}")
        return ""


def process_single_input(
    input_file: Path,
    output_file: Path,
    config_path: str,
    strategy: ContextStrategy,
    api_key: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    try:
        logger.info(f"Processing: {input_file}")
        with open(input_file) as f:
            input_data = DatasetInput(**json.load(f))
        if not input_data.fetched_content:
            logger.info(f"Fetching content from {input_data.url}")
            input_data.fetched_content = fetch_url_content(input_data.url)
            with open(input_file, "w", encoding="utf-8") as f:
                json.dump(input_data.model_dump(), f, indent=2, ensure_ascii=False)
            logger.info("Updated input file with fetched content")

        settings = AppSettings(
            llm=LLMSettings(),
            context_strategy=strategy,
        )

        logger.info(f"Loading agent registry from {config_path}")
        registry = AgentRegistry(config_path, api_key=api_key)
        logger.info(f"Loaded {len(registry.get_all_agent_ids())} agents")

        logger.info("Starting execution")
        orchestrator = Orchestrator(registry, settings)
        outputs = orchestrator.run(input_data)
        raw_lm_usage = orchestrator.get_lm_usage()
        raw_agent_usage = orchestrator.get_per_agent_usage()
        token_usage = format_token_usage(
            {
                "by_model": raw_lm_usage,
                "by_agent": raw_agent_usage,
            }
        )

        logger.info("Merging results")
        merger = MetadataMerger()
        result = merger.merge(outputs, input_data=input_data.model_dump())
        warnings = merger.get_warnings()
        for w in warnings:
            logger.warning(f"Warning: {w}")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Writing output to {output_file}")

        final_output = {
            "metadata": result,
            "token_usage": token_usage,
            "processed_at": datetime.now().isoformat(),
            "input_file": str(input_file),
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_output, f, indent=2, ensure_ascii=False)

        logger.info(f"Completed: {output_file}")
        return token_usage

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {input_file}: {e}")
        raise
    except Exception as e:
        logger.error(f"Pipeline failed for {input_file}: {e}")
        raise


def main():
    args = parse_args()
    setup_logging()
    logger = logging.getLogger(__name__)

    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)

    input_files = resolve_input_files(args.input)
    is_batch = len(input_files) > 1

    output_base = ensure_output_dir(args.output, is_batch)

    api_key = os.environ.get("LLM_API_KEY", "")
    strategy = (
        ContextStrategy.ACCUMULATIVE
        if args.strategy == "accumulative"
        else ContextStrategy.LAYERED
    )

    total_usage: dict[str, Any] = {}
    results_summary: list[dict[str, Any]] = []

    output_file = None
    for idx, input_file in enumerate(input_files, 1):
        if is_batch:
            logger.info(
                f"\n{'=' * 60}\nProcessing file {idx}/{len(input_files)}: {input_file}\n{'=' * 60}"
            )

        if is_batch:
            output_file = output_base / f"{input_file.stem}_enriched.json"
        else:
            if args.output:
                output_file = output_base
            else:
                output_dir = Path(__file__).parent / "output"
                output_dir.mkdir(parents=True, exist_ok=True)
                output_file = output_dir / f"{input_file.stem}_enriched.json"

        token_usage = process_single_input(
            input_file=input_file,
            output_file=output_file,
            config_path=args.config,
            strategy=strategy,
            api_key=api_key,
            logger=logger,
        )

        results_summary.append(
            {
                "input": str(input_file),
                "output": str(output_file),
                "tokens": token_usage["total"],
            }
        )

        for model, stats in token_usage["by_model"].items():
            if model not in total_usage:
                total_usage[model] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                }
            total_usage[model]["prompt_tokens"] += stats["prompt_tokens"]
            total_usage[model]["completion_tokens"] += stats["completion_tokens"]
            total_usage[model]["total_tokens"] += stats["total_tokens"]

    if is_batch:
        summary_file = output_base / "_batch_summary.json"
        grand_total = {
            "prompt_tokens": sum(m["prompt_tokens"] for m in total_usage.values()),
            "completion_tokens": sum(
                m["completion_tokens"] for m in total_usage.values()
            ),
            "total_tokens": sum(m["total_tokens"] for m in total_usage.values()),
        }

        batch_summary = {
            "processed_at": datetime.now().isoformat(),
            "total_files": len(input_files),
            "results": results_summary,
            "aggregate_token_usage": {
                "by_model": total_usage,
                "grand_total": grand_total,
            },
        }

        with open(summary_file, "w") as f:
            json.dump(batch_summary, f, indent=2, ensure_ascii=False)

        logger.info(f"\n{'=' * 60}")
        logger.info("BATCH PROCESSING COMPLETE")
        logger.info(f"{'=' * 60}")
        logger.info(f"Files processed: {len(input_files)}")
        logger.info(f"Total tokens used: {grand_total['total_tokens']:,}")
        logger.info(f"  - Prompt tokens: {grand_total['prompt_tokens']:,}")
        logger.info(f"  - Completion tokens: {grand_total['completion_tokens']:,}")
        logger.info(f"Summary saved to: {summary_file}")
    else:
        logger.info(f"\nToken usage saved in output file: {output_file}")

    logger.info("Pipeline completed successfully")


if __name__ == "__main__":
    main()
