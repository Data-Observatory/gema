"""Agents tab — per-agent model/temperature, visible and editable, plus a
full-config JSON download/upload for backup or hand-editing outside the app.

Model selection lives on AgentConfig.model (a free-text string passed
straight through to the LLM client — see llm/factory.py). There is no
enumerable "known models per provider" list anywhere in this project's
config (config/providers.yaml only has connection settings, not model
catalogs), so this is deliberately a text input with example placeholder
text, not a dropdown — a fabricated model list would go stale and could
imply only listed models work.

Only model/temperature are edited via the per-agent cards; everything
else (prompt, provider, fields, depends_on) is shown read-only in a
collapsed "Advanced" section for transparency. Download/Upload operate on
the *entire* PipelineConfig, not just what the cards expose — a user can
download, hand-edit anything (including the prompt) in a text editor, and
re-upload; the cards are a friendly view, not the only way to change
things. Upload re-validates through PipelineConfig's own validators
(cross-references between agents/providers included) before applying
anything, so a bad upload never leaves a partially-applied config.

Edits here are session-only, mutating the shared PipelineConfig object in
place — never written back to config/agents.yaml (see visor/settings.py's
module docstring for why that file must stay off-limits to a
non-programmer). Download the JSON to keep changes for next time.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from nicegui import events, ui

from metadata_enricher.config.models import PipelineConfig

logger = logging.getLogger(__name__)


def render_agents(container: ui.element, pipeline_config: PipelineConfig) -> None:
    container.clear()
    with container:
        ui.label("Agents").classes("text-h5")
        ui.label(
            "Each step of the pipeline is handled by one agent. Set which model it "
            "uses below — leave blank to use the provider's default model."
        ).classes("text-caption")

        with ui.row().classes("q-mt-sm"):
            ui.button(
                "Download configuration (JSON)", on_click=lambda: _download(pipeline_config)
            ).props("outline").mark("agents-download")
            async def _on_upload(e: events.UploadEventArguments) -> None:
                await _handle_upload(e, pipeline_config, cards.refresh)

            ui.upload(
                label="Upload configuration (JSON)",
                auto_upload=True,
                on_upload=_on_upload,
            ).classes("w-64").mark("agents-upload")

        @ui.refreshable
        def cards() -> None:
            model_inputs: dict[str, ui.input] = {}
            temp_inputs: dict[str, ui.number] = {}

            for agent in pipeline_config.agents:
                with ui.card().classes("w-full q-mt-md"):
                    ui.label(agent.name).classes("text-subtitle1 text-bold")
                    if agent.description:
                        ui.label(agent.description).classes("text-caption")

                    model_inputs[agent.id] = (
                        ui.input(
                            "Model",
                            value=agent.model or "",
                            placeholder="e.g. gpt-4o, claude-opus-4, glm-4.6 — blank = provider default",
                        )
                        .classes("w-full")
                        .mark(f"agent-model-{agent.id}")
                    )
                    temp_inputs[agent.id] = (
                        ui.number(
                            "Temperature",
                            value=agent.temperature,
                            min=0.0,
                            max=2.0,
                            step=0.1,
                        )
                        .classes("w-40")
                        .mark(f"agent-temperature-{agent.id}")
                    )

                    with ui.expansion("Advanced", icon="tune").classes("w-full q-mt-sm"):
                        ui.label(f"Provider: {agent.provider}")
                        ui.label(f"Runs after: {', '.join(agent.depends_on) or '(nothing — runs first)'}")
                        ui.label(f"Produces fields: {', '.join(agent.fields)}")
                        ui.label("Prompt (read-only here — edit via the downloaded JSON)").classes(
                            "text-caption q-mt-sm"
                        )
                        ui.code(agent.prompt, language=None).classes("w-full")

            def _save() -> None:
                for agent in pipeline_config.agents:
                    agent.model = model_inputs[agent.id].value.strip() or None
                    agent.temperature = temp_inputs[agent.id].value
                ui.notify("Agent settings updated for this session", type="positive")

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
