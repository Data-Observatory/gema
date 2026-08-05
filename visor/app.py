"""visor entry point — settings gate -> run form -> result, one NiceGUI page.

Imports only from metadata_enricher (the library), never from
metadata_enricher.cli — see visor/AGENTS.md / the visor plan doc for why.
`ui.run(native=True)` (this file's default) vs `ui.run(host=..., port=...)`
(VISOR_NATIVE=0) is a one-line switch on the same app code, so this can run
hosted later without a rewrite.
"""

from __future__ import annotations

import logging
import os

from nicegui import ui

from metadata_enricher.pipeline import PipelineResult
from visor.bootstrap import load_pipeline_config
from visor.pages.result_page import render_result
from visor.pages.run_page import render_run_form
from visor.pages.settings_page import render_settings
from visor.settings import VisorSettings, apply_to_environ, load_settings, missing_required

logger = logging.getLogger(__name__)

_pipeline_config, _schema, _config_error = load_pipeline_config()


@ui.page("/")
def main_page() -> None:
    content = ui.column().classes("w-full max-w-3xl mx-auto q-pa-md")

    if _pipeline_config is None or _schema is None:
        with content:
            ui.label("Configuration problem").classes("text-h5 text-negative")
            ui.label(_config_error or "Unknown configuration error")
        return

    pipeline_config = _pipeline_config
    schema = _schema

    def show_run() -> None:
        render_run_form(content, pipeline_config, on_result=show_result, on_error=show_error)

    def show_result(result: PipelineResult) -> None:
        render_result(content, result, schema, on_back=show_run)

    def show_error(message: str) -> None:
        content.clear()
        with content:
            ui.label("Something went wrong").classes("text-h5 text-negative")
            ui.label(message)
            ui.button("Back", on_click=show_run)

    def show_settings() -> None:
        settings = load_settings()
        render_settings(content, pipeline_config, settings, on_saved=_after_settings_saved)

    def _after_settings_saved(settings: VisorSettings) -> None:
        apply_to_environ(settings)
        show_run()

    settings = load_settings()
    apply_to_environ(settings)
    if missing_required(pipeline_config, settings):
        show_settings()
    else:
        show_run()


def run() -> None:
    native = os.environ.get("VISOR_NATIVE", "1") != "0"
    if native:
        ui.run(title="Visor", native=True, reload=False, show=True, window_size=(1100, 800))
    else:
        ui.run(
            title="Visor",
            host="0.0.0.0",
            port=int(os.environ.get("VISOR_PORT", "8080")),
            reload=False,
            show=False,
        )


if __name__ in {"__main__", "__mp_main__"}:
    run()
