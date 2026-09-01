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
from visor.i18n import t
from visor.session_settings import save_session_settings
from visor.settings import (
    VisorSettings,
    addable_providers,
    agents_using_provider,
    dataverse_uses_provider,
    optional_env_vars,
)

# Internal, language-independent sentinel for the add-provider picker's
# "not one of the known pool entries" choice -- only its displayed label
# is translated; pool_by_name never has a real provider under this key,
# so the equality check in _apply_choice() below stays unambiguous.
_CUSTOM_PROVIDER = "__custom__"


def render_settings(
    container: ui.element,
    pipeline_config: PipelineConfig,
    current: VisorSettings,
    on_saved: Callable[[VisorSettings], None],
    known_providers: list[ProviderConfig] | None = None,
    dataverse_export_config: DataverseExportConfig | None = None,
    on_changed: Callable[[], None] | None = None,
) -> Callable[[], object]:
    """Returns a zero-arg refresh function, same contract as
    render_run_form() and render_agents() -- see app.py's shared
    broadcast wiring for why every tab needs one, and why it is
    deliberately NOT this tab's own `body.refresh`: a Settings edit panel
    can be sitting open with a typed-but-unsaved API key or Base URL, and
    a full body rebuild triggered by an unrelated Agents-tab edit would
    silently collapse it back to the last-saved value. The only thing
    Settings actually needs to reflect from elsewhere is each provider's
    "used by" caption (an agent's provider reassignment), so the returned
    function updates just that label's text in place instead.

    *on_changed* fires whenever this tab mutates pipeline_config.providers
    outside of the Save & Continue button (adding or removing a provider)
    -- app.py wires it to refresh every other tab too, so e.g. the Agents
    tab's provider dropdown picks up a just-added provider without
    needing its own unrelated action to force a re-render first.
    """
    container.clear()
    known_providers = known_providers or []
    # Name of a provider just added via the mini-form, so its row opens
    # already expanded on the next render instead of the user having to
    # find and click its own edit icon right after adding it. Consumed
    # (popped) on read so it only auto-expands once.
    just_added: list[str] = []
    # Populated fresh by every body() run, read by _sync_used_by_hints()
    # (this tab's cross-tab-facing listener, see the docstring above) --
    # kept at this outer scope so it survives body.refresh() rebuilding
    # the actual ui.label objects underneath it.
    hint_labels: dict[str, ui.label] = {}

    def _used_by_hint(provider: ProviderConfig) -> str:
        used_by = list(agents_using_provider(pipeline_config, provider.name))
        if dataverse_uses_provider(dataverse_export_config, provider.name):
            used_by.append(t("settings.providers.dataverse_subject_classifier"))
        return (
            t("settings.providers.used_by", agents=", ".join(used_by))
            if used_by
            else t("settings.providers.not_used")
        )

    def _sync_used_by_hints() -> None:
        if {p.name for p in pipeline_config.providers} != set(hint_labels):
            # The provider list itself changed shape (e.g. an Agents-tab
            # config upload replaced pipeline_config.providers wholesale)
            # -- patching label text in place can't add or remove rows,
            # and _save() below indexes url_inputs by every *current*
            # provider name, so a stale set left over from the last
            # body() render would raise KeyError the next time
            # Save & Continue is clicked. A full rebuild is the only
            # correct response here; it only fires on this rare, explicit
            # bulk replace, never on the routine "an agent's provider
            # changed" path this listener otherwise handles without
            # disturbing an open edit panel.
            body.refresh()
            return
        for provider in pipeline_config.providers:
            label = hint_labels.get(provider.name)
            if label is not None:
                label.text = _used_by_hint(provider)

    with container:
        ui.label(t("settings.title")).classes("text-h5")
        ui.label(t("settings.intro")).classes("text-caption")

        @ui.refreshable
        def body() -> None:
            env_inputs: dict[str, ui.input] = {}
            url_inputs: dict[str, ui.input] = {}
            # First provider (in list order) to render a given api_key_env
            # -- every later provider sharing that same env var edits the
            # exact same secret slot in os.environ, so it must not get its
            # own independent password field: two separate widgets both
            # claiming to be "the" value of e.g. OPENROUTER_API_KEY would
            # silently collide in env_inputs (last one rendered wins the
            # dict slot), discarding whatever was typed into the other one
            # the moment Save & Continue is clicked.
            env_var_owner: dict[str, str] = {}
            auto_expand = just_added.pop() if just_added else None
            hint_labels.clear()

            with ui.card().classes("w-full q-mt-md"):
                ui.label(t("settings.providers.title")).classes("text-subtitle1 text-bold")
                ui.label(t("settings.providers.intro")).classes("text-caption")

                for provider in pipeline_config.providers:
                    hint = _used_by_hint(provider)

                    edit_panel_ref: list[ui.column] = []

                    def _toggle_edit(ref: list[ui.column] = edit_panel_ref) -> None:
                        ref[0].set_visibility(not ref[0].visible)

                    def _remove(name: str = provider.name) -> None:
                        users = [a.id for a in pipeline_config.agents if a.provider == name]
                        if dataverse_uses_provider(dataverse_export_config, name):
                            users.append(t("settings.providers.dataverse_subject_classifier"))
                        if users:
                            ui.notify(
                                t("settings.providers.remove_blocked", name=name, users=", ".join(users)),
                                type="negative",
                            )
                            return
                        pipeline_config.providers[:] = [
                            p for p in pipeline_config.providers if p.name != name
                        ]
                        if pipeline_config.default_provider == name:
                            # PipelineConfig.default_provider is never read
                            # for routing (see this module's own docstring)
                            # but IS cross-validated against providers on
                            # reconstruction (PipelineConfig._validate_
                            # references) -- left dangling here, a later
                            # download-then-reupload of this exact,
                            # currently-valid config (the app's own
                            # documented backup path) would reject it.
                            pipeline_config.default_provider = (
                                pipeline_config.providers[0].name if pipeline_config.providers else None
                            )
                        ui.notify(t("settings.providers.removed", name=name), type="positive")
                        body.refresh()
                        if on_changed is not None:
                            on_changed()

                    with ui.row().classes("w-full items-center q-mt-sm no-wrap"):
                        ui.label(provider.name).classes("text-bold")
                        hint_labels[provider.name] = ui.label(hint).classes(
                            "text-caption flex-grow ellipsis"
                        )
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
                            ui.input(t("settings.base_url.label"), value=provider.base_url or "")
                            .classes("w-full")
                            .mark(f"settings-provider-url-{provider.name}")
                        )
                        owner = env_var_owner.get(provider.api_key_env)
                        if owner is None:
                            env_var_owner[provider.api_key_env] = provider.name
                            key_input = (
                                ui.input(
                                    t("settings.key.label", env=provider.api_key_env),
                                    password=True,
                                    password_toggle_button=True,
                                    value=current.env.get(provider.api_key_env, ""),
                                )
                                .classes("w-full")
                                .mark(f"settings-input-{provider.api_key_env}")
                            )
                            env_inputs[provider.api_key_env] = key_input
                        else:
                            ui.label(t("settings.key.shared", provider=owner)).classes("text-caption")
                    url_inputs[provider.name] = url_input

                ui.separator().classes("q-my-md")

                add_panel_ref: list[ui.column] = []

                def _toggle_add(ref: list[ui.column] = add_panel_ref) -> None:
                    ref[0].set_visibility(not ref[0].visible)

                with ui.row().classes("w-full items-center no-wrap"):
                    ui.label(t("settings.add_provider.title")).classes("text-subtitle2 text-bold flex-grow")
                    ui.button(icon="add", on_click=_toggle_add).props("flat round dense").mark(
                        "settings-add-provider-toggle"
                    )

                add_panel = ui.column().classes("w-full")
                add_panel.set_visibility(False)
                add_panel_ref.append(add_panel)
                with add_panel:
                    ui.label(t("settings.add_provider.help")).classes("text-caption")

                    pool = addable_providers(known_providers, pipeline_config)
                    pool_by_name = {p.name: p for p in pool}
                    choice_options = {p.name: p.name for p in pool}
                    choice_options[_CUSTOM_PROVIDER] = t("settings.add_provider.custom")

                    choice_select = ui.select(
                        choice_options, value=_CUSTOM_PROVIDER, label=t("settings.add_provider.provider_label")
                    ).classes("w-full").mark("settings-add-provider-choice")
                    name_input = (
                        ui.input(t("settings.add_provider.name_label"))
                        .classes("w-full")
                        .mark("settings-add-provider-name")
                    )
                    url_new_input = (
                        ui.input(t("settings.add_provider.url_label"))
                        .classes("w-full")
                        .mark("settings-add-provider-url")
                    )
                    env_name_input = (
                        ui.input(t("settings.add_provider.env_label"))
                        .classes("w-full")
                        .mark("settings-add-provider-env-name")
                    )
                    key_new_input = (
                        ui.input(
                            t("settings.add_provider.key_label"), password=True, password_toggle_button=True
                        )
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
                            ui.notify(t("settings.add_provider.name_required"), type="negative")
                            return
                        # Checked live against pipeline_config.providers, not
                        # a snapshot taken when this panel was rendered:
                        # body.refresh() is fire-and-forget (see this
                        # module's own docstring), so a double-click on
                        # Submit before the rebuild lands would otherwise
                        # still see a stale, pre-add name set and let a
                        # second provider through under the same name --
                        # exactly what PipelineConfig's duplicate-provider-
                        # name validator now rejects on next reload.
                        if any(p.name == name for p in pipeline_config.providers):
                            ui.notify(t("settings.add_provider.duplicate", name=name), type="negative")
                            return
                        env_name_value = (
                            env_name_input.value.strip()
                            or f"{name.upper().replace('-', '_').replace(' ', '_')}_API_KEY"
                        )
                        shares_env_with_existing = any(
                            p.api_key_env == env_name_value for p in pipeline_config.providers
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
                            # other key here. One real secret slot exists
                            # per env var name (os.environ has no concept
                            # of "per provider"), so typing a key here for
                            # an env var an existing provider already uses
                            # replaces that provider's key too -- warn
                            # rather than silently overwrite it.
                            if shares_env_with_existing and current.env.get(env_name_value):
                                ui.notify(
                                    t("settings.add_provider.key_overwrite_warning", env=env_name_value),
                                    type="warning",
                                )
                            current.env[env_name_value] = key_new_input.value
                        just_added[:] = [name]
                        ui.notify(t("settings.add_provider.added", name=name), type="positive")
                        body.refresh()
                        if on_changed is not None:
                            on_changed()

                    ui.button(t("settings.add_provider.submit"), on_click=_add_provider).classes(
                        "q-mt-sm"
                    ).mark("settings-add-provider-submit")

            ui.label(t("settings.orcid.title")).classes("text-subtitle2 q-mt-md")
            for env_name in optional_env_vars():
                # A provider's api_key_env is free text (the add-provider
                # form, or an uploaded agents.yaml) -- if it happens to
                # collide with a fixed ORCID var name, the provider loop
                # above already claimed this env_inputs slot and rendered
                # the real input; rendering a second one here would hit
                # the exact same collision this module fixed for providers
                # sharing an api_key_env with each other.
                if env_name in env_inputs:
                    ui.label(t("settings.key.shared_env", env=env_name)).classes("text-caption")
                    continue
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

            def _providers_with_unassigned_keys(settings: VisorSettings) -> list[str]:
                """Providers with a saved, non-empty key that no agent (and
                not the Dataverse subject classifier) is actually assigned
                to yet -- closes the loop from the other direction of the
                Agents tab's own "used by: ..." hint: a key saved here with
                nothing pointed at it is a likely papercut (the user meant
                to switch an agent to it and hasn't yet), not a silent
                no-op like an unused ORCID var."""
                names = []
                for provider in pipeline_config.providers:
                    if not settings.env.get(provider.api_key_env):
                        continue
                    if agents_using_provider(pipeline_config, provider.name):
                        continue
                    if dataverse_uses_provider(dataverse_export_config, provider.name):
                        continue
                    names.append(provider.name)
                return names

            def _save() -> None:
                nonlocal current
                for provider in pipeline_config.providers:
                    provider.base_url = url_inputs[provider.name].value.strip() or None
                # Starts from the previously-saved env, not a blank dict:
                # env_inputs only has a field for a provider currently in
                # pipeline_config.providers (plus the fixed ORCID vars), so
                # rebuilding from scratch would silently drop a saved key
                # for any provider removed from the list earlier in this
                # same session (e.g. right after the Agents tab's bulk
                # switch makes it unused) the moment Save is next clicked
                # for an unrelated reason -- switching an agent back to
                # that provider later would then re-gate the Run tab for
                # no reason the user could see coming.
                merged_env = dict(current.env)
                for name, field in env_inputs.items():
                    if field.value:
                        merged_env[name] = field.value
                    else:
                        merged_env.pop(name, None)
                new_settings = VisorSettings(
                    default_provider=current.default_provider,
                    env=merged_env,
                )
                save_session_settings(new_settings)
                unassigned = _providers_with_unassigned_keys(new_settings)
                # body.refresh() below re-renders every input's initial value
                # from `current` -- without reassigning it first, the just-
                # saved edit (e.g. a corrected API key) would visually revert
                # to the pre-save value the moment Settings is redrawn, even
                # though the correct value is already on disk.
                current = new_settings
                ui.notify(t("settings.saved"), type="positive")
                if unassigned:
                    ui.notify(
                        t("settings.unassigned_key_hint", providers=", ".join(unassigned)),
                        type="warning",
                    )
                body.refresh()
                on_saved(new_settings)

            ui.button(t("settings.save"), on_click=_save).classes("q-mt-md").mark("settings-save")

        body()

    return _sync_used_by_hints
