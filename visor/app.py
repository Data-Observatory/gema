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

from nicegui import events, ui

from visor.bootstrap import (
    load_dataverse_export_config_safe,
    load_pipeline_config,
    load_providers_pool_safe,
)
from metadata_enricher.llm.factory import reset_client_cache
from visor.i18n import LANGUAGES, current_language, set_language, t
from visor.pages.agents_page import render_agents
from visor.pages.run_page import render_run_form
from visor.pages.settings_page import render_settings
from visor.settings import VisorSettings, apply_to_environ, load_settings, storage_secret

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
        ui.label(t("app.config_error.title")).classes("text-h5 text-negative")
        ui.label(_config_error or t("app.config_error.unknown"))
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

    with ui.column().classes("w-full max-w-3xl mx-auto q-pa-md"):

        def _on_language_change(e: events.ValueChangeEventArguments[str]) -> None:
            set_language(e.value)
            # Every label/caption below was rendered once, synchronously, in
            # whatever language was active at the time -- there is no
            # reactive binding to flip them individually, so a full reload
            # (re-running main_page() from scratch) is the simplest correct
            # way to apply a language switch. This does drop in-progress
            # form input / an in-flight run, same tradeoff as navigating
            # away and back.
            ui.navigate.reload()

        ui.select(
            LANGUAGES,
            value=current_language(),
            on_change=_on_language_change,
        ).props("dense outlined").classes("self-end").mark("language-select")

        with ui.tabs().classes("w-full") as tabs:
            settings_tab = ui.tab(t("app.tab.settings")).mark("tab-settings")
            agents_tab = ui.tab(t("app.tab.agents")).mark("tab-agents")
            run_tab = ui.tab(t("app.tab.run")).mark("tab-run")

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
        dataverse_export_config=dataverse_export_config,
    )

    def _after_settings_saved(settings: VisorSettings) -> None:
        apply_to_environ(settings)
        # create_llm_client()'s cache key is provider+model+temperature+...
        # -- never the API key's actual value -- so an already-cached
        # client for the same provider/model keeps using whatever key was
        # set when it was first created. Without this, changing a key here
        # has no effect until the whole visor process restarts.
        reset_client_cache()
        refresh_run_tab()
        tabs.set_value(run_tab)

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
    # Needed for app.storage.user (the per-browser language preference) --
    # without it NiceGUI raises at first access instead of silently no-op'ing.
    secret = storage_secret()
    if native:
        ui.run(
            title="Visor",
            native=True,
            reload=False,
            show=True,
            window_size=(1100, 800),
            storage_secret=secret,
        )
    else:
        ui.run(
            title="Visor",
            host="0.0.0.0",
            port=int(os.environ.get("VISOR_PORT", "8080")),
            reload=False,
            show=False,
            # Lets NiceGUI correctly prefix its asset/websocket URLs when
            # served behind a reverse proxy on a subpath (e.g. Caddy's
            # /visor/*, stripped before reaching this process) — confirmed
            # live against a real Caddy handle_path setup, including the
            # socket.io handshake, not just static asset links.
            root_path=os.environ.get("VISOR_ROOT_PATH", ""),
            storage_secret=secret,
        )


if __name__ in {"__main__", "__mp_main__"}:
    run()
