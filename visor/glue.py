"""Glue between visor's UI state and the metadata_enricher library.

Deliberately thin: every object here is imported straight from
metadata_enricher (Pipeline, PipelineConfig, FilesystemInputSource) — never
from metadata_enricher.cli. This module exists only to turn "JSON text from
a form/paste/upload" into a temp file FilesystemInputSource can read, the
same way a user's real input file would be read by `gema process`.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from metadata_enricher.agents.registry import LLMClientFactory
from metadata_enricher.config.models import PipelineConfig
from metadata_enricher.input_sources.filesystem import FilesystemInputSource
from metadata_enricher.pipeline import Pipeline, PipelineResult
from visor.log_stream import activate_run, deactivate_run


def write_temp_input_from_text(json_text: str) -> Path:
    """Write raw JSON text (pasted, or an uploaded file's decoded bytes) to a
    temp file, unchanged — FilesystemInputSource.fetch() is the only JSON
    parser in this path, matching how a real input file is read."""
    fd = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    try:
        fd.write(json_text)
    finally:
        fd.close()
    return Path(fd.name)


def write_temp_input_from_dict(data: dict[str, Any]) -> Path:
    """Same as write_temp_input_from_text, for the structured run form's
    field values collected into a dict."""
    return write_temp_input_from_text(json.dumps(data))


def run_single(
    pipeline_config: PipelineConfig,
    input_path: Path,
    *,
    max_workers: int | None = None,
    llm_factory: LLMClientFactory | None = None,
    run_id: str | None = None,
) -> PipelineResult:
    """Run the pipeline on the single resource at *input_path*.

    Mirrors cli.py's process() command's wiring (construct Pipeline, run
    against a FilesystemInputSource) for exactly one resource — visor never
    writes output to disk itself, it renders PipelineResult and offers a
    download instead.

    run_id (from visor.log_stream.LogCapture.run_id) marks this call's
    thread -- and, via orchestrator.py's contextvars propagation, every
    per-wave worker thread it spawns -- so this session's log capture
    doesn't also pick up a concurrent hosted session's lines. Omitted in
    non-visor callers (there are none today, but this stays optional
    rather than visor-only-required).
    """
    token = activate_run(run_id) if run_id is not None else None
    try:
        pipeline = Pipeline(
            config=pipeline_config,
            llm_factory=llm_factory,
            max_workers=max_workers if max_workers is not None else pipeline_config.max_workers,
        )
        source = FilesystemInputSource()
        results = pipeline.run(source, pattern=str(input_path))
        if not results:
            raise RuntimeError("Pipeline produced no result for the submitted resource")
        return results[0]
    finally:
        if token is not None:
            deactivate_run(token)
