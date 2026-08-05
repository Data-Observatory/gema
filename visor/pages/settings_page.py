"""Settings screen — first-run gate for local secrets.

Never shows a saved value back after save (masked inputs, no echo). Never
writes to .env or config/agents.yaml — see visor/settings.py.
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from metadata_enricher.config.models import PipelineConfig
from visor.settings import VisorSettings, optional_env_vars, required_env_vars, save_settings


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
            "Your API key is saved only on this computer and used only to talk "
            "to the LLM provider you choose below — it is never bundled with "
            "the app or shared with anyone else."
        ).classes("text-caption")

        provider_names = [p.name for p in pipeline_config.providers]
        default_select = ui.select(
            provider_names,
            value=current.default_provider or pipeline_config.default_provider,
            label="Default provider",
        ).classes("w-full")

        env_inputs: dict[str, ui.input] = {}

        ui.label("Required").classes("text-subtitle2 q-mt-md")
        for env_name in required_env_vars(pipeline_config):
            env_inputs[env_name] = ui.input(
                env_name,
                password=True,
                password_toggle_button=True,
                value=current.env.get(env_name, ""),
            ).classes("w-full").mark(f"settings-input-{env_name}")

        ui.label("Optional — lets ORCID be searched by author name").classes(
            "text-subtitle2 q-mt-md"
        )
        for env_name in optional_env_vars():
            env_inputs[env_name] = ui.input(
                env_name,
                password=True,
                password_toggle_button=True,
                value=current.env.get(env_name, ""),
            ).classes("w-full").mark(f"settings-input-{env_name}")

        def _save() -> None:
            new_settings = VisorSettings(
                default_provider=default_select.value,
                env={name: field.value for name, field in env_inputs.items() if field.value},
            )
            save_settings(new_settings)
            ui.notify("Settings saved", type="positive")
            on_saved(new_settings)

        ui.button("Save & Continue", on_click=_save).classes("q-mt-md").mark("settings-save")
