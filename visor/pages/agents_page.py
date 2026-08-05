"""Agents tab — per-agent provider/model/temperature, visible and editable,
plus a full-config JSON download/upload for backup or hand-editing outside
the app.

Provider is a select populated from pipeline_config.providers — always a
valid choice by construction, no free-text typo risk. Model selection
lives on AgentConfig.model (a free-text string passed straight through to
the LLM client — see llm/factory.py). There is no enumerable "known
models per provider" list anywhere in this project's config
(config/providers.yaml only has connection settings, not model catalogs),
so Model is a combobox (ui.select with with_input=True): MODEL_CATALOG
below offers a curated, best-effort, non-exhaustive shortlist per known
provider name, but typing any other model id is always accepted — a
fabricated "complete" list would go stale and could wrongly imply only
listed models work. Switching an agent's Provider refreshes that agent's
Model options to match. Whichever provider each agent is set to here is
what Settings' "used by: ..." captions reflect — the two tabs describe
the same underlying assignment from two different angles.

Prompt/fields/depends_on are read-only in a collapsed "Advanced" section
for transparency. Download/Upload operate on the *entire* PipelineConfig,
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
from typing import Callable

from nicegui import events, ui

from metadata_enricher.config.models import DataverseExportConfig, PipelineConfig

logger = logging.getLogger(__name__)

# Curated, non-exhaustive — keyed by provider *name* as declared in
# config/providers.yaml. Unknown/custom provider names (e.g. one just
# added via Settings) get an empty list, which still works fine with
# with_input=True: the combobox just has no suggestions to offer.
MODEL_CATALOG: dict[str, list[str]] = {
    "zai-coding-plan": ["glm-5.2", "glm-4.7", "glm-4.7-flash", "glm-4.6"],
    "opencode": ["gpt-4o", "claude-sonnet-5", "glm-4.7"],
    "openai": ["gpt-5.1", "gpt-5.1-mini", "gpt-4o", "gpt-4o-mini", "o3"],
    "anthropic": ["claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-haiku-4-5-20251001"],
}


def _model_options(provider_name: str, current_model: str) -> list[str]:
    """The catalog for *provider_name*, plus *current_model* if it isn't
    already in it — ui.select requires its initial value to be a member of
    options even with with_input=True, and a model already configured
    (e.g. hand-edited into agents.yaml, or just not in our curated list)
    must never make the page fail to render."""
    options = list(MODEL_CATALOG.get(provider_name, []))
    if current_model not in options:
        options.append(current_model)
    return options


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
                                _model_options(agent.provider, agent.model or ""),
                                value=agent.model or "",
                                label="Model",
                                with_input=True,
                                new_value_mode="add-unique",
                            )
                            .classes("flex-grow")
                            .mark(f"agent-model-{agent.id}")
                        )
                        provider_selects[agent.id].on_value_change(
                            lambda e, aid=agent.id: model_inputs[aid].set_options(
                                _model_options(e.value, model_inputs[aid].value or "")
                            )
                        )
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
                                _model_options(
                                    dataverse_export_config.agent.provider,
                                    dataverse_export_config.agent.model or "",
                                ),
                                value=dataverse_export_config.agent.model or "",
                                label="Model — a fast/cheap tier is enough for a 14-way classification",
                                with_input=True,
                                new_value_mode="add-unique",
                            )
                            .classes("flex-grow")
                            .mark("dataverse-export-model")
                        )
                        _dataverse_model_select = dataverse_model_input

                        def _on_dataverse_provider_change(e: events.ValueChangeEventArguments[str]) -> None:
                            _dataverse_model_select.set_options(
                                _model_options(e.value, _dataverse_model_select.value or "")
                            )

                        dataverse_provider_select.on_value_change(_on_dataverse_provider_change)
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
    pipeline_config.validate_pids = validated.validate_pids
    pipeline_config.validate_pids_live = validated.validate_pids_live

    refresh_cards()
    ui.notify(f"Applied uploaded configuration ({len(validated.agents)} agents)", type="positive")
