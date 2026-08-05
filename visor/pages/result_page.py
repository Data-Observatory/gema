"""Result screen — renders a PipelineResult, offers a JSON download.

Pure consumption of the existing PipelineResult.success/.error/.warnings
contract (metadata_enricher/pipeline.py) — no new pipeline behavior here.
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from metadata_enricher.output import OutputWriter
from metadata_enricher.pipeline import PipelineResult
from metadata_enricher.schemas.base import Schema


def render_result(
    container: ui.element,
    result: PipelineResult,
    schema: Schema,
    on_back: Callable[[], None],
) -> None:
    container.clear()
    with container:
        if result.success:
            assert result.document is not None
            json_str = OutputWriter(schema).format_json(result.document)

            if result.warnings:
                with ui.card().classes("bg-warning w-full"):
                    ui.label("Some fields are incomplete or a PID didn't check out:").classes(
                        "text-bold"
                    )
                    for warning in result.warnings:
                        ui.label(f"- {warning}")

            ui.label("Result").classes("text-h5 q-mt-md").mark("result-success")
            ui.code(json_str, language="json").classes("w-full").mark("result-json")

            ui.button(
                "Download JSON",
                # Explicit bytes, not str: NiceGUI's test-simulation
                # Download.content() override skips the str->bytes
                # conversion the real implementation does, and would
                # misread a plain string as a URL/path instead of content
                # (caught by visor/tests/test_app_e2e.py's real click-through
                # test). bytes behaves identically in the real app either way.
                on_click=lambda: ui.download.content(
                    json_str.encode("utf-8"), filename="metadata.json", media_type="application/json"
                ),
            ).classes("q-mt-md").mark("result-download")
        else:
            ui.label("This resource could not be processed").classes(
                "text-h5 text-negative"
            ).mark("result-failure")
            ui.label(result.error or "Unknown error").mark("result-error")

        ui.button("Run another", on_click=on_back).classes("q-mt-md").mark("result-back")
