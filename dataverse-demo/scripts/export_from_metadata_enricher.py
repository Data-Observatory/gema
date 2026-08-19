#!/usr/bin/env python3
"""Convert a gema DataCite JSON output into Dataverse's native
dataset JSON, ready for smoke_test.sh's "create dataset" step.

Run from the repo root (needs the same venv metadata_enricher lives in):

    uv run python dataverse-demo/scripts/export_from_metadata_enricher.py \
        tests/fixtures/golden/expected/sample_input01.json \
        --output dataverse-demo/scripts/example_dataset.json

Without --classify, Subject classification is skipped (config's `enabled`
still applies if you do pass it, but this flag lets you skip the LLM call
— and its cost — when you just want a quick structural check). With
--classify, uses config/dataverse_export.yaml's provider/model, which
needs that provider's API key set (same as running gema itself).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from metadata_enricher.config.loader import load_config  # noqa: E402
from metadata_enricher.exporters.dataverse import load_dataverse_export_config, to_dataverse_json  # noqa: E402
from metadata_enricher.types import MetadataDocument  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", type=Path, help="A gema DataCite JSON output file")
    parser.add_argument("--output", type=Path, default=Path("dataset.json"))
    parser.add_argument(
        "--classify",
        action="store_true",
        help="Run the real Subject classification LLM call (needs an API key set — "
        "see config/dataverse_export.yaml for which provider/model)",
    )
    parser.add_argument(
        "--pipeline-config",
        type=Path,
        default=REPO_ROOT / "config" / "agents.yaml",
        help="Where to find provider connection details for --classify",
    )
    parser.add_argument(
        "--export-config",
        type=Path,
        default=REPO_ROOT / "config" / "dataverse_export.yaml",
    )
    args = parser.parse_args()

    data = json.loads(args.input_json.read_text(encoding="utf-8"))
    document = MetadataDocument()
    for key, value in data.items():
        document.set_field(key, value)

    export_config = load_dataverse_export_config(args.export_config)
    provider = None
    if args.classify:
        pipeline_config = load_config(args.pipeline_config)
        export_config.validate_provider_exists({p.name for p in pipeline_config.providers})
        provider = next(p for p in pipeline_config.providers if p.name == export_config.agent.provider)
    else:
        export_config.enabled = False

    result = to_dataverse_json(document, export_config, provider)

    args.output.write_text(json.dumps(result.dataset_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    if result.warnings:
        print("Warnings (dataset will still be created, but check these):")
        for warning in result.warnings:
            print(f"  - {warning}")
    if result.token_usage.total_tokens:
        print(f"Tokens used: {result.token_usage.total_tokens} total")


if __name__ == "__main__":
    main()
