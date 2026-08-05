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

"Add a provider" lets a user add a brand-new entry to
pipeline_config.providers (session-only, same mutate-in-place pattern as
every other edit in this app) — either picked from a known pool
(config/providers.yaml, autofills name/base URL/key env name) or fully
custom for a provider that pool doesn't have. Once added, it shows up in
the regular per-provider key-input list below automatically, since that
list is always built fresh from pipeline_config.providers on every
refresh — no special-casing needed for "the new one".
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from metadata_enricher.config.models import PipelineConfig, ProviderConfig
from visor.settings import (
    VisorSettings,
    addable_providers,
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
    known_providers: list[ProviderConfig] | None = None,
) -> None:
    container.clear()
    known_providers = known_providers or []
    known_by_name = {p.name: p for p in known_providers}

    with container:
        ui.label("Settings").classes("text-h5")
        ui.label(
            "API keys are saved only on this computer and used only to talk "
            "to the provider each key belongs to — never bundled with the "
            "app or shared with anyone else."
        ).classes("text-caption")

        @ui.refreshable
        def body() -> None:
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

            with ui.card().classes("w-full q-mt-md"):
                ui.label("Add a provider").classes("text-subtitle1 text-bold")
                ui.label(
                    "Pick one from the list to autofill its connection details, "
                    "or choose \"Other (custom)\" for a provider not listed here."
                ).classes("text-caption")

                existing_names = {p.name for p in pipeline_config.providers}
                pool_names = [p.name for p in addable_providers(known_providers, pipeline_config)]
                choice_options = [*pool_names, "Other (custom)"]

                choice_select = ui.select(choice_options, value=choice_options[0], label="Provider").classes(
                    "w-full"
                ).mark("settings-add-provider-choice")
                name_input = ui.input("Name").classes("w-full").mark("settings-add-provider-name")
                url_input = ui.input("Base URL").classes("w-full").mark("settings-add-provider-url")
                env_name_input = (
                    ui.input("Environment variable name for its key")
                    .classes("w-full")
                    .mark("settings-add-provider-env-name")
                )
                key_input = (
                    ui.input("API key", password=True, password_toggle_button=True)
                    .classes("w-full")
                    .mark("settings-add-provider-key")
                )

                def _apply_choice() -> None:
                    preset = known_by_name.get(choice_select.value)
                    if preset is not None:
                        name_input.value = preset.name
                        url_input.value = preset.base_url or ""
                        env_name_input.value = preset.api_key_env
                    else:
                        name_input.value = ""
                        url_input.value = ""
                        env_name_input.value = ""

                choice_select.on_value_change(_apply_choice)
                _apply_choice()

                def _add_provider() -> None:
                    name = name_input.value.strip()
                    if not name:
                        ui.notify("Provider name is required", type="negative")
                        return
                    if name in existing_names:
                        ui.notify(f"Provider '{name}' already exists", type="negative")
                        return
                    env_name_value = (
                        env_name_input.value.strip()
                        or f"{name.upper().replace('-', '_').replace(' ', '_')}_API_KEY"
                    )
                    pipeline_config.providers.append(
                        ProviderConfig(
                            name=name,
                            base_url=url_input.value.strip() or None,
                            api_key_env=env_name_value,
                        )
                    )
                    if key_input.value:
                        # Pre-fill so the user doesn't have to type the key
                        # twice — it still isn't saved to disk until Save
                        # & Continue is clicked, same as every other key here.
                        current.env[env_name_value] = key_input.value
                    ui.notify(f"Added provider '{name}' — set its key below and Save", type="positive")
                    body.refresh()

                ui.button("Add provider", on_click=_add_provider).classes("q-mt-sm").mark(
                    "settings-add-provider-submit"
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

        body()
