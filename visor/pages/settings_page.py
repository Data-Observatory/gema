"""Settings screen — first-run gate for local secrets.

Never shows a saved value back after save (masked inputs, no echo). Never
writes to .env or config/agents.yaml — see visor/settings.py.

No "default provider" selector here — that field never actually chose
which provider an agent runs with (each agent's own `provider`, set in the
Agents tab, is authoritative; `PipelineConfig.default_provider` is only
ever read for a CLI display label). Keeping it in Settings alongside a
per-agent provider selector was confusing with no functional payoff, so
it's gone; VisorSettings still accepts a saved value for backward
compatibility with an existing settings.json, it's just never shown here.
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from metadata_enricher.config.models import PipelineConfig
from visor.settings import (
    VisorSettings,
    all_provider_env_vars,
    optional_env_vars,
    providers_using,
    save_settings,
)


def render_settings(
    container: ui.element,
    pipeline_config: PipelineConfig,
    current: VisorSettings,
    on_saved: Callable[[VisorSettings], None],
) -> None:
    container.clear()
    with container:
        ui.label("Settings").classes("text-h5")
        ui.label(
            "API keys are saved only on this computer and used only to talk "
            "to the provider each key belongs to — never bundled with the "
            "app or shared with anyone else."
        ).classes("text-caption")

        env_inputs: dict[str, ui.input] = {}

        ui.label("API keys").classes("text-subtitle2 q-mt-md")
        ui.label(
            "One per provider. Which provider each agent actually uses is set "
            "in the Agents tab — enter a key here for any provider you plan "
            "to use, even if no agent is assigned to it yet."
        ).classes("text-caption")
        for env_name in all_provider_env_vars(pipeline_config):
            used_by = providers_using(pipeline_config, env_name)
            hint = f"used by: {', '.join(used_by)}" if used_by else "not currently used by any agent"
            env_inputs[env_name] = (
                ui.input(
                    f"{env_name} ({hint})",
                    password=True,
                    password_toggle_button=True,
                    value=current.env.get(env_name, ""),
                )
                .classes("w-full")
                .mark(f"settings-input-{env_name}")
            )

        ui.label("Optional — lets ORCID be searched by author name").classes(
            "text-subtitle2 q-mt-md"
        )
        for env_name in optional_env_vars():
            env_inputs[env_name] = (
                ui.input(
                    env_name,
                    password=True,
                    password_toggle_button=True,
                    value=current.env.get(env_name, ""),
                )
                .classes("w-full")
                .mark(f"settings-input-{env_name}")
            )

        def _save() -> None:
            new_settings = VisorSettings(
                default_provider=current.default_provider,
                env={name: field.value for name, field in env_inputs.items() if field.value},
            )
            save_settings(new_settings)
            ui.notify("Settings saved", type="positive")
            on_saved(new_settings)

        ui.button("Save & Continue", on_click=_save).classes("q-mt-md").mark("settings-save")
