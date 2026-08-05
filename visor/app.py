"""visor entry point — Settings / Agents / Run as always-visible, freely
navigable tabs (not a locked wizard): the user can hop between configuring
things and running a resource at will.

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

from visor.bootstrap import load_dataverse_export_config_safe, load_pipeline_config
from visor.pages.agents_page import render_agents
from visor.pages.run_page import render_run_form
from visor.pages.settings_page import render_settings
from visor.settings import VisorSettings, apply_to_environ, load_settings

logger = logging.getLogger(__name__)

_pipeline_config, _schema, _config_error = load_pipeline_config()
# Optional extra — a failure here must never block the rest of the app
# (unlike _pipeline_config, which is core functionality). Logged, and
# the Dataverse-export UI just doesn't show up if this is None.
_dataverse_export_config, _dataverse_export_error = load_dataverse_export_config_safe()
if _dataverse_export_error is not None:
    logger.warning("Dataverse export unavailable: %s", _dataverse_export_error)


@ui.page("/")
def main_page() -> None:
    if _pipeline_config is None or _schema is None:
        ui.label("Configuration problem").classes("text-h5 text-negative")
        ui.label(_config_error or "Unknown configuration error")
        return

    pipeline_config = _pipeline_config
    schema = _schema

    apply_to_environ(load_settings())

    with ui.column().classes("w-full max-w-3xl mx-auto q-pa-md"):
        with ui.tabs().classes("w-full") as tabs:
            settings_tab = ui.tab("Settings").mark("tab-settings")
            agents_tab = ui.tab("Agents").mark("tab-agents")
            run_tab = ui.tab("Run").mark("tab-run")

        with ui.tab_panels(tabs, value=run_tab).classes("w-full"):
            settings_panel = ui.tab_panel(settings_tab)
            agents_panel = ui.tab_panel(agents_tab)
            run_panel = ui.tab_panel(run_tab)

    def _go_to_settings() -> None:
        tabs.set_value(settings_tab)

    refresh_run_tab = render_run_form(
        run_panel,
        pipeline_config,
        schema,
        current_settings=load_settings,
        on_go_to_settings=_go_to_settings,
        dataverse_export_config=_dataverse_export_config,
    )

    def _after_settings_saved(settings: VisorSettings) -> None:
        apply_to_environ(settings)
        refresh_run_tab()
        tabs.set_value(run_tab)

    render_settings(settings_panel, pipeline_config, load_settings(), on_saved=_after_settings_saved)
    render_agents(agents_panel, pipeline_config, _dataverse_export_config)


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
