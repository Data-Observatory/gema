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

Providers and their keys are one single block: every already-configured
provider is a compact row (name + "used by" hint) with an edit (pencil)
icon that reveals its Base URL/key fields, and a delete icon that removes
it — refused if any agent still uses it, since agents reference providers
by name. The "+" next to "Add a provider" reveals the same mini-form as
before (pick from the config/providers.yaml pool to autofill, or fully
custom). Nothing is written until Save & Continue, same as every other
field on this page. Rows and the add-form start collapsed on purpose —
this is deliberately a "nothing pre-opened, everything one click away"
list rather than a wall of always-visible inputs.
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from metadata_enricher.config.models import DataverseExportConfig, PipelineConfig, ProviderConfig
from visor.settings import (
    VisorSettings,
    addable_providers,
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
    dataverse_export_config: DataverseExportConfig | None = None,
) -> None:
    container.clear()
    known_providers = known_providers or []
    # Name of a provider just added via the mini-form, so its row opens
    # already expanded on the next render instead of the user having to
    # find and click its own edit icon right after adding it. Consumed
    # (popped) on read so it only auto-expands once.
    just_added: list[str] = []

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
            url_inputs: dict[str, ui.input] = {}
            auto_expand = just_added.pop() if just_added else None

            with ui.card().classes("w-full q-mt-md"):
                ui.label("Providers").classes("text-subtitle1 text-bold")
                ui.label(
                    "Connection details and API key for every provider — which "
                    "one each agent actually uses is set in the Agents tab."
                ).classes("text-caption")

                for provider in pipeline_config.providers:
                    used_by = providers_using(pipeline_config, provider.api_key_env)
                    hint = f"used by: {', '.join(used_by)}" if used_by else "not currently used by any agent"

                    edit_panel_ref: list[ui.column] = []

                    def _toggle_edit(ref: list[ui.column] = edit_panel_ref) -> None:
                        ref[0].set_visibility(not ref[0].visible)

                    def _remove(name: str = provider.name) -> None:
                        users = [a.id for a in pipeline_config.agents if a.provider == name]
                        if dataverse_export_config is not None and dataverse_export_config.agent.provider == name:
                            users.append("dataverse export's Subject Classifier")
                        if users:
                            ui.notify(f"Can't remove '{name}' — used by: {', '.join(users)}", type="negative")
                            return
                        pipeline_config.providers[:] = [
                            p for p in pipeline_config.providers if p.name != name
                        ]
                        ui.notify(f"Removed provider '{name}'", type="positive")
                        body.refresh()

                    with ui.row().classes("w-full items-center q-mt-sm no-wrap"):
                        ui.label(provider.name).classes("text-bold")
                        ui.label(hint).classes("text-caption flex-grow ellipsis")
                        ui.button(icon="edit", on_click=_toggle_edit).props(
                            "flat round dense"
                        ).mark(f"settings-provider-edit-{provider.name}")
                        ui.button(icon="delete", on_click=_remove).props(
                            "flat round dense"
                        ).mark(f"settings-provider-remove-{provider.name}")

                    edit_panel = ui.column().classes("w-full q-pl-md")
                    edit_panel.set_visibility(provider.name == auto_expand)
                    edit_panel_ref.append(edit_panel)
                    with edit_panel:
                        url_input = (
                            ui.input("Base URL", value=provider.base_url or "")
                            .classes("w-full")
                            .mark(f"settings-provider-url-{provider.name}")
                        )
                        key_input = (
                            ui.input(
                                f"{provider.api_key_env} key",
                                password=True,
                                password_toggle_button=True,
                                value=current.env.get(provider.api_key_env, ""),
                            )
                            .classes("w-full")
                            .mark(f"settings-input-{provider.api_key_env}")
                        )
                    url_inputs[provider.name] = url_input
                    env_inputs[provider.api_key_env] = key_input

                ui.separator().classes("q-my-md")

                add_panel_ref: list[ui.column] = []

                def _toggle_add(ref: list[ui.column] = add_panel_ref) -> None:
                    ref[0].set_visibility(not ref[0].visible)

                with ui.row().classes("w-full items-center no-wrap"):
                    ui.label("Add a provider").classes("text-subtitle2 text-bold flex-grow")
                    ui.button(icon="add", on_click=_toggle_add).props("flat round dense").mark(
                        "settings-add-provider-toggle"
                    )

                add_panel = ui.column().classes("w-full")
                add_panel.set_visibility(False)
                add_panel_ref.append(add_panel)
                with add_panel:
                    ui.label(
                        "Pick one from the list to autofill its connection details, "
                        "or choose \"Other (custom)\" for a provider not listed here."
                    ).classes("text-caption")

                    existing_names = {p.name for p in pipeline_config.providers}
                    pool = addable_providers(known_providers, pipeline_config)
                    pool_by_name = {p.name: p for p in pool}
                    CUSTOM = "Other (custom)"
                    choice_options = [*[p.name for p in pool], CUSTOM]

                    choice_select = ui.select(choice_options, value=CUSTOM, label="Provider").classes(
                        "w-full"
                    ).mark("settings-add-provider-choice")
                    name_input = ui.input("Name").classes("w-full").mark("settings-add-provider-name")
                    url_new_input = ui.input("Base URL").classes("w-full").mark("settings-add-provider-url")
                    env_name_input = (
                        ui.input("Environment variable name for its key")
                        .classes("w-full")
                        .mark("settings-add-provider-env-name")
                    )
                    key_new_input = (
                        ui.input("API key", password=True, password_toggle_button=True)
                        .classes("w-full")
                        .mark("settings-add-provider-key")
                    )

                    def _apply_choice() -> None:
                        preset = pool_by_name.get(choice_select.value)
                        if preset is not None:
                            name_input.value = preset.name
                            url_new_input.value = preset.base_url or ""
                            env_name_input.value = preset.api_key_env
                        else:
                            name_input.value = ""
                            url_new_input.value = ""
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
                                base_url=url_new_input.value.strip() or None,
                                api_key_env=env_name_value,
                            )
                        )
                        if key_new_input.value:
                            # Pre-fill so the user doesn't have to type the
                            # key twice — it still isn't saved to disk until
                            # Save & Continue is clicked, same as every
                            # other key here.
                            current.env[env_name_value] = key_new_input.value
                        just_added[:] = [name]
                        ui.notify(f"Added provider '{name}' — set its key below and Save", type="positive")
                        body.refresh()

                    ui.button("Add provider", on_click=_add_provider).classes("q-mt-sm").mark(
                        "settings-add-provider-submit"
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
                nonlocal current
                for provider in pipeline_config.providers:
                    provider.base_url = url_inputs[provider.name].value.strip() or None
                new_settings = VisorSettings(
                    default_provider=current.default_provider,
                    env={name: field.value for name, field in env_inputs.items() if field.value},
                )
                save_settings(new_settings)
                # body.refresh() below re-renders every input's initial value
                # from `current` -- without reassigning it first, the just-
                # saved edit (e.g. a corrected API key) would visually revert
                # to the pre-save value the moment Settings is redrawn, even
                # though the correct value is already on disk.
                current = new_settings
                ui.notify("Settings saved", type="positive")
                body.refresh()
                on_saved(new_settings)

            ui.button("Save & Continue", on_click=_save).classes("q-mt-md").mark("settings-save")

        body()
