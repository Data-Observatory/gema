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
from nicegui.elements.tabs import Tab, Tabs

from visor.bootstrap import (
    load_dataverse_export_config_safe,
    load_pipeline_config,
    load_providers_pool_safe,
)
from visor.pages.agents_page import render_agents
from visor.pages.run_page import render_run_form
from visor.pages.settings_page import render_settings
from visor.settings import VisorSettings, apply_to_environ, load_settings

logger = logging.getLogger(__name__)

_pipeline_config, _schema, _config_error = load_pipeline_config()
# Optional extras — a failure in either must never block the rest of the
# app (unlike _pipeline_config, which is core functionality).
_dataverse_export_config, _dataverse_export_error = load_dataverse_export_config_safe()
if _dataverse_export_error is not None:
    logger.warning("Dataverse export unavailable: %s", _dataverse_export_error)
_known_providers = load_providers_pool_safe()


@ui.page("/")
def main_page() -> None:
    if _pipeline_config is None or _schema is None:
        ui.label("Configuration problem").classes("text-h5 text-negative")
        ui.label(_config_error or "Unknown configuration error")
        return

    # Deep copies, not aliases -- main_page() runs once per browser
    # connection, and agents_page.py / settings_page.py both mutate these
    # objects in place (per-agent provider/model/temperature, the provider
    # list, the Dataverse export card). In native mode there's only ever
    # one session so this changes nothing observable; in hosted mode
    # (VISOR_NATIVE=0, multiple people connecting to the same process) a
    # bare alias would let one user's edit leak into every other user's
    # session.
    pipeline_config = _pipeline_config.model_copy(deep=True)
    dataverse_export_config = (
        _dataverse_export_config.model_copy(deep=True)
        if _dataverse_export_config is not None
        else None
    )
    schema = _schema

    apply_to_environ(load_settings())

    # Operator-facing lockdown for untrusted hosted guests (e.g. workshop
    # attendees over Tailscale): Settings/Agents can leak API key presence
    # and let a guest repoint every other guest's pipeline, so when this is
    # set they're not created at all -- just the Run panel's content,
    # directly, no tabs bar needed for a single tab.
    hosted_guest = os.environ.get("VISOR_HOSTED_GUEST", "0") == "1"

    tabs: Tabs | None = None
    settings_tab: Tab | None = None
    run_tab: Tab | None = None

    with ui.column().classes("w-full max-w-3xl mx-auto q-pa-md"):
        if hosted_guest:
            run_panel: ui.element = ui.column().classes("w-full")
        else:
            with ui.tabs().classes("w-full") as tabs:
                settings_tab = ui.tab("Settings").mark("tab-settings")
                agents_tab = ui.tab("Agents").mark("tab-agents")
                run_tab = ui.tab("Run").mark("tab-run")

            with ui.tab_panels(tabs, value=run_tab).classes("w-full"):
                settings_panel = ui.tab_panel(settings_tab)
                agents_panel = ui.tab_panel(agents_tab)
                run_panel = ui.tab_panel(run_tab)

    def _go_to_settings() -> None:
        if tabs is None or settings_tab is None:
            ui.notify(
                "Settings are managed by whoever is hosting this session.",
                type="warning",
            )
            return
        tabs.set_value(settings_tab)

    refresh_run_tab = render_run_form(
        run_panel,
        pipeline_config,
        schema,
        current_settings=load_settings,
        on_go_to_settings=_go_to_settings,
        dataverse_export_config=dataverse_export_config,
    )

    if hosted_guest:
        return

    # Narrowed to plain local names (not `tabs`/`run_tab` themselves) so the
    # closure below captures a value mypy knows is non-optional -- narrowing
    # from an `assert` on the outer variable doesn't carry into a nested
    # function's body.
    assert tabs is not None and run_tab is not None
    non_hosted_tabs: Tabs = tabs
    non_hosted_run_tab: Tab = run_tab

    def _after_settings_saved(settings: VisorSettings) -> None:
        apply_to_environ(settings)
        refresh_run_tab()
        non_hosted_tabs.set_value(non_hosted_run_tab)

    render_settings(
        settings_panel,
        pipeline_config,
        load_settings(),
        on_saved=_after_settings_saved,
        known_providers=_known_providers,
        dataverse_export_config=dataverse_export_config,
    )
    render_agents(agents_panel, pipeline_config, dataverse_export_config)


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
