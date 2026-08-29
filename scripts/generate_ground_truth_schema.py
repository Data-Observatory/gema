#!/usr/bin/env python3
"""Dump DataCiteOutputModel's pydantic v2 JSON Schema to a file, for editor
autocomplete/inline validation while hand-editing ground-truth JSON or
metadata_template.json -- no custom form UI needed for that.

Usage:
    uv run python scripts/generate_ground_truth_schema.py
"""

from __future__ import annotations

import json
from pathlib import Path

from metadata_enricher.schemas.datacite import DataCiteOutputModel

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "tests/fixtures/do_catalog/ground_truth.schema.json"
)


def main() -> None:
    schema = DataCiteOutputModel.model_json_schema()
    OUTPUT_PATH.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
