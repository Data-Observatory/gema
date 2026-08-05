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

"Add a provider" doubles as "add or edit a provider": the picker lists
every already-configured provider *and* every not-yet-added pool entry
(config/providers.yaml) in one list, plus "Other (custom)". Picking an
already-configured one prefills its real current name/base URL/key env
name so it can be edited in place (submit updates that ProviderConfig
rather than appending a duplicate); picking a pool entry autofills the
same fields as a starting point for a new one; "Other (custom)" starts
blank. Session-only, same mutate-in-place pattern as every other edit in
this app. Once added or edited, it shows up in the regular per-provider
key-input list below automatically, since that list is always built
fresh from pipeline_config.providers on every refresh — no
special-casing needed for "the new one".
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
                ui.label("Add or edit a provider").classes("text-subtitle1 text-bold")
                ui.label(
                    "Pick an already-configured provider to edit its connection "
                    "details, pick one from the pool to autofill and add it, or "
                    "choose \"Other (custom)\" for a provider not listed here."
                ).classes("text-caption")

                existing_names = {p.name for p in pipeline_config.providers}
                # Existing providers first (so they're not "separated" from
                # the pool), then not-yet-added pool entries, then custom.
                pool_names = [p.name for p in addable_providers(known_providers, pipeline_config)]
                choice_options = [*sorted(existing_names), *pool_names, "Other (custom)"]
                # Pool entries as a baseline, overridden by the real
                # current config for anything already added — the
                # configured provider's own fields are authoritative.
                known_by_name: dict[str, ProviderConfig] = {p.name: p for p in known_providers}
                known_by_name.update({p.name: p for p in pipeline_config.providers})

                CUSTOM = "Other (custom)"
                choice_select = ui.select(choice_options, value=CUSTOM, label="Provider").classes(
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
                submit_button = ui.button("Add provider").classes("q-mt-sm").mark(
                    "settings-add-provider-submit"
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
                    submit_button.text = (
                        "Update provider" if choice_select.value in existing_names else "Add provider"
                    )

                choice_select.on_value_change(_apply_choice)
                _apply_choice()

                def _add_or_update_provider() -> None:
                    name = name_input.value.strip()
                    if not name:
                        ui.notify("Provider name is required", type="negative")
                        return
                    selected = choice_select.value
                    env_name_value = (
                        env_name_input.value.strip()
                        or f"{name.upper().replace('-', '_').replace(' ', '_')}_API_KEY"
                    )
                    is_editing = selected != CUSTOM and selected in existing_names
                    if is_editing:
                        if name != selected and name in existing_names:
                            ui.notify(f"Provider '{name}' already exists", type="negative")
                            return
                        provider = next(p for p in pipeline_config.providers if p.name == selected)
                        provider.name = name
                        provider.base_url = url_input.value.strip() or None
                        provider.api_key_env = env_name_value
                        message = f"Updated provider '{name}'"
                    else:
                        if name in existing_names:
                            ui.notify(f"Provider '{name}' already exists", type="negative")
                            return
                        pipeline_config.providers.append(
                            ProviderConfig(
                                name=name,
                                base_url=url_input.value.strip() or None,
                                api_key_env=env_name_value,
                            )
                        )
                        message = f"Added provider '{name}' — set its key below and Save"
                    if key_input.value:
                        # Pre-fill so the user doesn't have to type the key
                        # twice — it still isn't saved to disk until Save
                        # & Continue is clicked, same as every other key here.
                        current.env[env_name_value] = key_input.value
                    ui.notify(message, type="positive")
                    body.refresh()

                submit_button.on_click(_add_or_update_provider)

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
