"""Agents tab — per-agent provider/model/temperature, visible and editable,
plus a full-config JSON download/upload for backup or hand-editing outside
the app.

Provider is a select populated from pipeline_config.providers — always a
valid choice by construction, no free-text typo risk. Model selection
lives on AgentConfig.model (a free-text string passed straight through to
the LLM client — see llm/factory.py) and is a combobox (ui.select with
with_input=True): no options until "Refresh models" is clicked, which
fetches the real list from that provider's own `/models` endpoint (see
model_catalog.py) using whatever key is saved in Settings for it — never
a hardcoded/curated list, since that would go stale and wrongly imply
only listed models work. Typing any other model id is always accepted
regardless of whether a refresh has happened. Whichever provider each
agent is set to here is what Settings' "used by: ..." captions reflect —
the two tabs describe the same underlying assignment from two different
angles.

Prompt/fields/depends_on (and tools/extra_body, when an agent sets them)
are read-only in a collapsed "Advanced" section for transparency.

A "Pipeline behavior" card above the agent cards exposes the
PipelineConfig-level toggles (enable_content_fetch, enable_doi_resolution,
enable_identifier_enrichment, validate_pids, validate_pids_live) as plain
checkboxes — previously only reachable by hand-editing the downloaded
JSON and re-uploading it.

Download/Upload operate on the *entire* PipelineConfig,
not just what the cards expose — a user can download, hand-edit anything
(including the prompt) in a text editor, and re-upload; the cards are a
friendly view, not the only way to change things. Upload re-validates
through PipelineConfig's own validators (cross-references between
agents/providers included) before applying anything, so a bad upload
never leaves a partially-applied config.

Edits here are session-only, mutating the shared PipelineConfig object in
place — never written back to config/agents.yaml (see visor/settings.py's
module docstring for why that file must stay off-limits to a
non-programmer). Download the JSON to keep changes for next time.

Below the 5 pipeline agent cards, a 6th card configures the Dataverse
export's one LLM-assisted step (Subject classification) — same
provider/model/temperature shape, plus an Enabled checkbox this is the
only card that has, since it's the one thing meant to be independently
toggleable (see exporters/dataverse.py). It never runs through the
orchestrator, so it's edited here but not part of pipeline_config.agents.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Callable

from nicegui import events, run, ui

from metadata_enricher.config.models import DataverseExportConfig, PipelineConfig, ProviderConfig
from visor.model_catalog import fetch_provider_models
from visor.settings import load_settings

logger = logging.getLogger(__name__)


def _model_options(options: list[str], current_model: str) -> list[str]:
    """*options* plus *current_model* if it isn't already in it — ui.select
    requires its initial/updated value to be a member of options even
    with with_input=True, and a model already configured (e.g.
    hand-edited into agents.yaml, or not in a freshly fetched list) must
    never make the page fail to render."""
    result = list(options)
    if current_model not in result:
        result.append(current_model)
    return result


def _resolve_api_key(provider: ProviderConfig) -> str | None:
    return load_settings().env.get(provider.api_key_env) or os.environ.get(provider.api_key_env)


async def _refresh_models(provider: ProviderConfig, model_select: ui.select) -> None:
    api_key = _resolve_api_key(provider)
    try:
        models = await run.io_bound(fetch_provider_models, provider, api_key)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, never fatal
        logger.warning("Could not fetch models for provider %s: %s", provider.name, exc)
        ui.notify(f"Could not fetch models for '{provider.name}': {exc}", type="negative")
        return
    if models is None:  # run.io_bound's typing allows None; fetch_provider_models never returns it
        models = []
    model_select.set_options(_model_options(models, model_select.value or ""))
    ui.notify(f"Loaded {len(models)} models for '{provider.name}'", type="positive")


def render_agents(
    container: ui.element,
    pipeline_config: PipelineConfig,
    dataverse_export_config: DataverseExportConfig | None = None,
) -> None:
    container.clear()
    with container:
        ui.label("Agents").classes("text-h5")
        ui.label(
            "Each step of the pipeline is handled by one agent. Set which provider "
            "and model it uses below — leave model blank to use the provider's "
            "default. Add the matching API key in the Settings tab."
        ).classes("text-caption")

        with ui.row().classes("q-mt-sm items-center"):
            ui.button(
                "Download configuration (JSON)", on_click=lambda: _download(pipeline_config)
            ).props("outline").mark("agents-download")

            async def _on_upload(e: events.UploadEventArguments) -> None:
                await _handle_upload(e, pipeline_config, cards.refresh)

            # flat + a fixed width keeps this beside Download instead of a
            # tall drop-zone with a big empty file-list area reserved below
            # the button — auto_upload means that list is never shown anyway.
            ui.upload(
                label="Upload configuration (JSON)",
                auto_upload=True,
                on_upload=_on_upload,
            ).props("flat bordered").classes("w-64").style("max-height: 44px; overflow: hidden").mark(
                "agents-upload"
            )

        @ui.refreshable
        def cards() -> None:
            # Recomputed on every refresh, not hoisted above the
            # refreshable — Upload can replace pipeline_config.providers
            # entirely, and this must reflect that on the next render.
            provider_names = [p.name for p in pipeline_config.providers]
            model_inputs: dict[str, ui.select] = {}
            temp_inputs: dict[str, ui.number] = {}
            provider_selects: dict[str, ui.select] = {}

            with ui.card().classes("w-full q-mt-md"):
                ui.label("Pipeline behavior").classes("text-subtitle1 text-bold")
                ui.label(
                    "These apply to the whole pipeline, not a single agent."
                ).classes("text-caption")

                content_fetch_checkbox = (
                    ui.checkbox(
                        "Fetch page content automatically",
                        value=pipeline_config.enable_content_fetch,
                    )
                    .tooltip(
                        "Fetches each resource's URL and feeds the page text to the "
                        "agents when they don't already have it."
                    )
                    .mark("pipeline-enable-content-fetch")
                )
                doi_resolution_checkbox = (
                    ui.checkbox(
                        "Resolve DOIs automatically",
                        value=pipeline_config.enable_doi_resolution,
                    )
                    .tooltip("Looks up a bare DOI to help fill in missing metadata.")
                    .mark("pipeline-enable-doi-resolution")
                )
                identifier_enrichment_checkbox = (
                    ui.checkbox(
                        "Enrich identifiers (ROR / ORCID / ISNI)",
                        value=pipeline_config.enable_identifier_enrichment,
                    )
                    .tooltip(
                        "Resolves ROR/ISNI identifiers for creators, publishers, and "
                        "funders the agents left blank."
                    )
                    .mark("pipeline-enable-identifier-enrichment")
                )
                validate_pids_checkbox = (
                    ui.checkbox(
                        "Validate persistent identifiers",
                        value=pipeline_config.validate_pids,
                    )
                    .mark("pipeline-validate-pids")
                )
                validate_pids_live_checkbox = (
                    ui.checkbox(
                        "Validate PIDs live (real network calls)",
                        value=pipeline_config.validate_pids_live,
                    )
                    .mark("pipeline-validate-pids-live")
                )

            for agent in pipeline_config.agents:
                with ui.card().classes("w-full q-mt-md"):
                    ui.label(agent.name).classes("text-subtitle1 text-bold")
                    if agent.description:
                        ui.label(agent.description).classes("text-caption")

                    with ui.row().classes("w-full items-end"):
                        provider_selects[agent.id] = (
                            ui.select(
                                provider_names,
                                value=agent.provider,
                                label="Provider",
                            )
                            .classes("w-48")
                            .mark(f"agent-provider-{agent.id}")
                        )
                        model_inputs[agent.id] = (
                            ui.select(
                                _model_options([], agent.model or ""),
                                value=agent.model or "",
                                label="Model",
                                with_input=True,
                                new_value_mode="add-unique",
                            )
                            .classes("flex-grow")
                            .mark(f"agent-model-{agent.id}")
                        )

                        def _refresh_for_agent(aid: str = agent.id) -> object:
                            provider = next(
                                (p for p in pipeline_config.providers if p.name == provider_selects[aid].value),
                                None,
                            )
                            if provider is None:
                                ui.notify("Pick a provider first", type="negative")
                                return None
                            return _refresh_models(provider, model_inputs[aid])

                        ui.button(icon="refresh", on_click=_refresh_for_agent).props("flat round").tooltip(
                            "Fetch this provider's real model list"
                        ).mark(f"agent-model-refresh-{agent.id}")
                        temp_inputs[agent.id] = (
                            ui.number(
                                "Temperature",
                                value=agent.temperature,
                                min=0.0,
                                max=2.0,
                                step=0.1,
                            )
                            .classes("w-32")
                            .mark(f"agent-temperature-{agent.id}")
                        )

                    with ui.expansion("Advanced", icon="tune").classes("w-full q-mt-sm"):
                        ui.label(f"Runs after: {', '.join(agent.depends_on) or '(nothing — runs first)'}")
                        ui.label(f"Produces fields: {', '.join(agent.fields)}")
                        if agent.tools:
                            ui.label(f"Tools: {', '.join(agent.tools)}")
                        if agent.extra_body:
                            ui.label(f"Extra request options: {agent.extra_body}")
                        ui.label("Prompt (read-only here — edit via the downloaded JSON)").classes(
                            "text-caption q-mt-sm"
                        )
                        ui.code(agent.prompt, language=None).classes("w-full")

            dataverse_enabled_checkbox = None
            dataverse_provider_select = None
            dataverse_model_input = None
            dataverse_temp_input = None
            if dataverse_export_config is not None:
                with ui.card().classes("w-full q-mt-md"):
                    ui.label("Dataverse Export — Subject Classifier").classes("text-subtitle1 text-bold")
                    ui.label(
                        "Optional: classifies this resource into Dataverse's required Subject "
                        "category when you download a Dataverse-format JSON. Turn off to always "
                        "use \"Other\" instead, with no extra LLM call."
                    ).classes("text-caption")

                    dataverse_enabled_checkbox = (
                        ui.checkbox("Enabled", value=dataverse_export_config.enabled)
                        .mark("dataverse-export-enabled")
                    )
                    with ui.row().classes("w-full items-end"):
                        dataverse_provider_select = (
                            ui.select(
                                provider_names,
                                value=dataverse_export_config.agent.provider,
                                label="Provider",
                            )
                            .classes("w-48")
                            .mark("dataverse-export-provider")
                        )
                        dataverse_model_input = (
                            ui.select(
                                _model_options([], dataverse_export_config.agent.model or ""),
                                value=dataverse_export_config.agent.model or "",
                                label="Model — a fast/cheap tier is enough for a 14-way classification",
                                with_input=True,
                                new_value_mode="add-unique",
                            )
                            .classes("flex-grow")
                            .mark("dataverse-export-model")
                        )
                        _dataverse_model_select = dataverse_model_input

                        def _refresh_dataverse_models() -> object:
                            provider = next(
                                (p for p in pipeline_config.providers if p.name == dataverse_provider_select.value),
                                None,
                            )
                            if provider is None:
                                ui.notify("Pick a provider first", type="negative")
                                return None
                            return _refresh_models(provider, _dataverse_model_select)

                        ui.button(icon="refresh", on_click=_refresh_dataverse_models).props(
                            "flat round"
                        ).tooltip("Fetch this provider's real model list").mark(
                            "dataverse-export-model-refresh"
                        )
                        dataverse_temp_input = (
                            ui.number(
                                "Temperature",
                                value=dataverse_export_config.agent.temperature,
                                min=0.0,
                                max=2.0,
                                step=0.1,
                            )
                            .classes("w-32")
                            .mark("dataverse-export-temperature")
                        )

            def _save() -> None:
                pipeline_config.enable_content_fetch = content_fetch_checkbox.value
                pipeline_config.enable_doi_resolution = doi_resolution_checkbox.value
                pipeline_config.enable_identifier_enrichment = identifier_enrichment_checkbox.value
                pipeline_config.validate_pids = validate_pids_checkbox.value
                pipeline_config.validate_pids_live = validate_pids_live_checkbox.value
                for agent in pipeline_config.agents:
                    agent.provider = provider_selects[agent.id].value
                    agent.model = model_inputs[agent.id].value.strip() or None
                    agent.temperature = temp_inputs[agent.id].value
                if dataverse_export_config is not None:
                    assert dataverse_enabled_checkbox is not None
                    assert dataverse_provider_select is not None
                    assert dataverse_model_input is not None
                    assert dataverse_temp_input is not None
                    dataverse_export_config.enabled = dataverse_enabled_checkbox.value
                    dataverse_export_config.agent.provider = dataverse_provider_select.value
                    dataverse_export_config.agent.model = dataverse_model_input.value.strip() or None
                    dataverse_export_config.agent.temperature = dataverse_temp_input.value
                ui.notify("Agent settings updated for this session", type="positive")
                cards.refresh()

            ui.button("Save changes", on_click=_save).classes("q-mt-md").mark("agents-save")

        cards()


def _download(pipeline_config: PipelineConfig) -> None:
    json_str = json.dumps(pipeline_config.model_dump(mode="json"), indent=2, ensure_ascii=False)
    ui.download.content(
        json_str.encode("utf-8"), filename="visor_agents_config.json", media_type="application/json"
    )


async def _handle_upload(
    e: events.UploadEventArguments, pipeline_config: PipelineConfig, refresh_cards: Callable[[], object]
) -> None:
    try:
        raw = await e.file.text()
        data = json.loads(raw)
        validated = PipelineConfig(**data)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not hidden
        logger.warning("Rejected uploaded agents config: %s", exc)
        ui.notify(f"Could not apply this file: {exc}", type="negative")
        return

    pipeline_config.schema_name = validated.schema_name
    pipeline_config.agents = validated.agents
    pipeline_config.providers = validated.providers
    pipeline_config.default_provider = validated.default_provider
    pipeline_config.strategies = validated.strategies
    pipeline_config.max_workers = validated.max_workers
    pipeline_config.enable_identifier_enrichment = validated.enable_identifier_enrichment
    pipeline_config.enable_content_fetch = validated.enable_content_fetch
    pipeline_config.enable_doi_resolution = validated.enable_doi_resolution
    pipeline_config.validate_pids = validated.validate_pids
    pipeline_config.validate_pids_live = validated.validate_pids_live

    refresh_cards()
    ui.notify(f"Applied uploaded configuration ({len(validated.agents)} agents)", type="positive")
