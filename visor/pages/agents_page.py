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
Reasoning effort is its own editable select, inline with provider/model/
temperature rather than tucked into Advanced -- it's a real per-run knob
(the thing to lower first if a Responses-API model runs slow), not
background detail.

A "switch provider for all agents" card above everything else sets every
agent card's provider select (and, if checked, the Dataverse card's) in
one click and tries to auto-pick a model for each via the same
model_catalog fetch the per-agent refresh button uses -- switching
providers one card at a time is what leaves an agent stranded on the old
provider and produces a confusing multi-provider Run-tab gate.

A "Pipeline behavior" card above the agent cards exposes the
PipelineConfig-level toggles (enable_content_fetch, enable_doi_resolution,
enable_identifier_enrichment, validate_pids, validate_pids_live,
validate_shacl_conformance) as plain checkboxes — previously only
reachable by hand-editing the downloaded JSON and re-uploading it.

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
from typing import Any, Callable, cast

from nicegui import events, run, ui

from metadata_enricher.config.models import (
    DataverseExportConfig,
    PipelineConfig,
    ProviderConfig,
    ReasoningEffort,
    find_model_override_elsewhere,
)
from metadata_enricher.llm.responses_client import UNSUPPORTED_EXTRA_BODY_KEYS_ON_RESPONSES
from visor.i18n import t
from visor.model_catalog import fetch_provider_models
from visor.session_settings import load_session_settings, save_session_settings
from visor.settings import VisorSettings

logger = logging.getLogger(__name__)

# UI sentinel, shared by the bulk effort select and each per-agent effort
# select, for "clear this agent's override -- use the provider/model
# cascade" -- distinct from AgentConfig.reasoning_effort's own real "None"
# (unset) and from "provider_default" (a real, explicit ReasoningEffort
# value meaning "omit the reasoning block entirely"). ui.select needs a
# concrete option value, so this stands in for the unset case.
_BULK_EFFORT_INHERIT = ""

# A second, distinct sentinel for the BULK select only -- found on review:
# once per-agent reasoning_effort became individually settable, defaulting
# the bulk select to _BULK_EFFORT_INHERIT meant every "change model for all
# agents" click also silently wiped any per-agent effort override that had
# nothing to do with the model change. This sentinel means "don't touch
# reasoning_effort at all" and is the bulk select's actual default; a user
# must deliberately pick _BULK_EFFORT_INHERIT (or a real level) to affect
# effort in bulk.
_BULK_EFFORT_KEEP_EXISTING = "__keep_existing__"


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
    return load_session_settings().env.get(provider.api_key_env) or os.environ.get(
        provider.api_key_env
    )


async def _refresh_models(provider: ProviderConfig, model_select: ui.select) -> None:
    api_key = _resolve_api_key(provider)
    try:
        models = await run.io_bound(fetch_provider_models, provider, api_key)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, never fatal
        logger.warning("Could not fetch models for provider %s: %s", provider.name, exc)
        ui.notify(t("agents.models.fetch_failed", provider=provider.name, error=exc), type="negative")
        return
    if models is None:  # run.io_bound's typing allows None; fetch_provider_models never returns it
        models = []
    model_select.set_options(_model_options(models, model_select.value or ""))
    ui.notify(t("agents.models.loaded", provider=provider.name, count=len(models)), type="positive")


def _persist_overrides(
    pipeline_config: PipelineConfig, dataverse_export_config: DataverseExportConfig | None
) -> None:
    """Snapshot the current in-memory provider/model/temperature/toggle
    state into settings.json (native) or this session's storage (hosted) --
    see visor/settings.py's apply_agent_overrides() for the read side.

    Always a full rewrite of agent_overrides from pipeline_config.agents,
    never a merge into whatever was previously saved -- so an agent
    removed by a config upload (or a repo agents.yaml change on next
    launch) never leaves a stale, unreachable entry behind. Preserves the
    current default_provider/env untouched, same as Settings' own _save()
    does for the fields it doesn't own.
    """
    current = load_session_settings()
    dataverse_override: dict[str, Any] | None = None
    if dataverse_export_config is not None:
        dataverse_override = {
            "enabled": dataverse_export_config.enabled,
            "provider": dataverse_export_config.agent.provider,
            "model": dataverse_export_config.agent.model,
            "temperature": dataverse_export_config.agent.temperature,
            "reasoning_effort": dataverse_export_config.agent.reasoning_effort,
        }
    save_session_settings(
        VisorSettings(
            default_provider=current.default_provider,
            env=current.env,
            agent_overrides={
                agent.id: {
                    "provider": agent.provider,
                    "model": agent.model,
                    "temperature": agent.temperature,
                    "reasoning_effort": agent.reasoning_effort,
                }
                for agent in pipeline_config.agents
            },
            dataverse_agent_override=dataverse_override,
            pipeline_behavior={
                "enable_content_fetch": pipeline_config.enable_content_fetch,
                "enable_doi_resolution": pipeline_config.enable_doi_resolution,
                "enable_identifier_enrichment": pipeline_config.enable_identifier_enrichment,
                "validate_pids": pipeline_config.validate_pids,
                "validate_pids_live": pipeline_config.validate_pids_live,
                "validate_shacl_conformance": pipeline_config.validate_shacl_conformance,
            },
        )
    )


def _warn_model_override_mismatches(
    pipeline_config: PipelineConfig, dataverse_export_config: DataverseExportConfig | None
) -> None:
    """Surface find_model_override_elsewhere() as a save-time UI warning --
    never blocking, since a provider genuinely not needing any override for
    a model is a normal, valid case. Without this, assigning a model to the
    wrong provider (the model field is free text, decoupled from the
    provider select right next to it -- see this module's docstring) fails
    silently: the run still starts, using that provider's plain default
    wire format, and only surfaces as a confusing runtime 400 from the LLM
    call itself. Checked at save time (not on every keystroke) since a
    mismatch is only meaningful once both fields have settled.

    Deduplicated by (model, provider, other_provider) before notifying --
    a bulk provider switch (see the "switch provider for all agents" card
    above) can put every agent onto the same wrong provider in one click,
    and one toast per agent for what's really one mistake is noise."""
    agents_and_dataverse = list(pipeline_config.agents)
    if dataverse_export_config is not None:
        agents_and_dataverse.append(dataverse_export_config.agent)
    seen: set[tuple[str, str, str]] = set()
    for agent in agents_and_dataverse:
        if not agent.model:
            continue
        other_provider = find_model_override_elsewhere(
            pipeline_config.providers, agent.model, agent.provider
        )
        if other_provider is None:
            continue
        key = (agent.model, agent.provider, other_provider)
        if key in seen:
            continue
        seen.add(key)
        ui.notify(
            t(
                "agents.model_provider_mismatch",
                model=agent.model,
                provider=agent.provider,
                other_provider=other_provider,
            ),
            type="warning",
        )


def _sanitize_extra_body_for_responses_api(
    agent_extra_body: dict[str, Any] | None,
    provider: ProviderConfig | None,
    model: str | None,
) -> dict[str, Any] | None:
    """Strip any extra_body key that ResponsesLLMClient would silently drop
    (and warn about, forever, on every call) for this agent's resolved
    api_style -- e.g. a stale ``{"thinking": {...}}`` left over from
    switching an agent's model away from deepseek-v4-flash onto a
    Responses-API model like muse-spark-1.3-contributor. Driven off the
    same UNSUPPORTED_EXTRA_BODY_KEYS_ON_RESPONSES list the client itself
    uses, keyed by resolved api_style rather than any specific model name,
    so this stays correct for any future Responses-API model, not just
    muse-spark. A no-op when there's nothing to strip, the agent isn't on
    the Responses API, or extra_body already has none of those keys."""
    if not agent_extra_body or provider is None or not model:
        return agent_extra_body
    if provider.effective_api_style(model) != "responses":
        return agent_extra_body
    cleaned = {
        key: value
        for key, value in agent_extra_body.items()
        if key not in UNSUPPORTED_EXTRA_BODY_KEYS_ON_RESPONSES
    }
    return cleaned or None


def sanitize_all_agents_extra_body(
    pipeline_config: PipelineConfig, dataverse_export_config: DataverseExportConfig | None
) -> None:
    """Runs _sanitize_extra_body_for_responses_api() over every agent (and
    the Dataverse classifier, if configured) -- called right before every
    _persist_overrides() in this module, so it catches a stale extra_body
    regardless of which control changed the (provider, model) pair: the
    per-agent Save changes button, the bulk provider switch, the bulk
    model/effort switch, or a config Upload.

    Not module-private (despite the leading-underscore-free name being the
    only thing that changes here) because app.py also calls this directly,
    once per browser connection/reload, right after apply_agent_overrides()
    +reconcile_provider_extra_body() -- found on review: without that call,
    a freshly loaded pipeline_config (nothing saved yet, or a saved
    provider/model override reconcile_provider_extra_body() doesn't know
    about) still had a stale extra_body until the user's first Save click,
    so the very request that reproduced the original bug report happened
    before this module's own save-time sanitize ever ran once."""
    agents_and_dataverse = list(pipeline_config.agents)
    if dataverse_export_config is not None:
        agents_and_dataverse.append(dataverse_export_config.agent)
    for agent in agents_and_dataverse:
        provider = next((p for p in pipeline_config.providers if p.name == agent.provider), None)
        agent.extra_body = _sanitize_extra_body_for_responses_api(
            agent.extra_body, provider, agent.model
        )


def render_agents(
    container: ui.element,
    pipeline_config: PipelineConfig,
    dataverse_export_config: DataverseExportConfig | None = None,
    on_changed: Callable[[], None] | None = None,
) -> Callable[[], object]:
    """Returns a zero-arg refresh function, same contract as
    render_run_form() and render_settings() -- see app.py's shared
    broadcast wiring for why every tab needs one, and why it is
    deliberately NOT this tab's own cards.refresh: a full rebuild would
    discard any not-yet-saved edit sitting in another agent's
    model/temperature field for a change (Settings adding or removing a
    provider) that only ever needs to update *options* lists. See
    _sync_provider_options() below for the actual returned function.

    *on_changed* fires whenever this tab commits a provider/model/agent
    change into pipeline_config (Save changes, the bulk provider switch,
    or a config upload) -- app.py wires it to refresh every other tab
    too, so e.g. the Run tab's missing-key gate reflects a provider
    switch made here immediately, without needing its own unrelated
    trigger (like a Settings save) to force a re-render first.
    """
    container.clear()
    # Populated (cleared and refilled) by every cards() run -- kept at
    # this outer scope, rather than as cards()-local variables, for two
    # separate reasons:
    #
    # 1. _sync_provider_options() below (this tab's cross-tab-facing
    #    listener) needs to reach the *current* selects after a Settings
    #    add/remove-provider broadcast, however many cards() renders
    #    have happened since it was defined.
    # 2. _apply_provider_to_all() is async and reads model_inputs /
    #    dataverse_model_input again *after* an `await` (the /models
    #    fetch) -- if those were still cards()-local, a cards.refresh()
    #    firing during that await (the user clicking "Save changes" or
    #    finishing an Upload while the fetch is in flight) would leave
    #    it holding orphaned, pre-refresh widgets: pipeline_config would
    #    get the new model, but the now-detached dropdowns would keep
    #    showing the old one, and the very next "Save changes" click
    #    would read those stale visible values straight back over the
    #    just-applied ones. Reading through these same outer containers
    #    after the await instead always sees whatever cards() most
    #    recently populated them with.
    provider_selects: dict[str, ui.select] = {}
    model_inputs: dict[str, ui.select] = {}
    bulk_provider_select_box: list[ui.select] = []
    dataverse_provider_select_box: list[ui.select | None] = [None]
    dataverse_model_input_box: list[ui.select | None] = [None]

    def _sync_provider_options() -> None:
        """This tab's cross-tab-facing listener (see app.py's broadcast
        wiring) -- deliberately NOT cards.refresh(): a full rebuild would
        also blow away any not-yet-saved edit sitting in another agent's
        model/temperature field, for a change (Settings adding or
        removing a provider) that only ever needs to update *options*
        lists, never any select's current value."""
        provider_names = [p.name for p in pipeline_config.providers]

        for select in provider_selects.values():
            select.set_options(_model_options(provider_names, select.value or ""))
        if bulk_provider_select_box:
            bulk_provider_select_box[0].set_options(provider_names)
        dataverse_provider_select = dataverse_provider_select_box[0]
        if dataverse_provider_select is not None:
            dataverse_provider_select.set_options(
                _model_options(provider_names, dataverse_provider_select.value or "")
            )

    with container:
        ui.label(t("agents.title")).classes("text-h5")
        ui.label(t("agents.intro")).classes("text-caption")

        with ui.row().classes("q-mt-sm items-center"):
            ui.button(
                t("agents.download"), on_click=lambda: _download(pipeline_config)
            ).props("outline").mark("agents-download")

            async def _on_upload(e: events.UploadEventArguments) -> None:
                await _handle_upload(e, pipeline_config, cards.refresh)
                # Harmless no-op snapshot when the upload was rejected
                # (pipeline_config is untouched in that case) -- otherwise
                # persists the newly uploaded provider/model/temperature
                # assignments the same way Save changes does. Dataverse
                # export config is never part of the uploaded JSON (see
                # _download()'s own docstring), so its saved override is
                # left exactly as it was.
                sanitize_all_agents_extra_body(pipeline_config, dataverse_export_config)
                _persist_overrides(pipeline_config, dataverse_export_config)
                if on_changed is not None:
                    on_changed()

            # flat + a fixed width keeps this beside Download instead of a
            # tall drop-zone with a big empty file-list area reserved below
            # the button — auto_upload means that list is never shown anyway.
            ui.upload(
                label=t("agents.upload"),
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
            temp_inputs: dict[str, ui.number] = {}
            effort_inputs: dict[str, ui.select] = {}
            provider_selects.clear()
            model_inputs.clear()

            # Every agent's (and, if present, the Dataverse classifier's)
            # provider, if they all currently agree on one -- pre-fills the
            # bulk selects below with reality instead of an empty
            # placeholder. Found on review: the provider select stayed
            # blank even right after Apply, since nothing ever wrote the
            # just-applied value back onto the select itself.
            _bulk_agent_providers = {a.provider for a in pipeline_config.agents}
            if dataverse_export_config is not None:
                _bulk_agent_providers.add(dataverse_export_config.agent.provider)
            current_common_provider = (
                next(iter(_bulk_agent_providers)) if len(_bulk_agent_providers) == 1 else None
            )

            with ui.card().classes("w-full q-mt-md"):
                ui.label(t("agents.bulk_provider.title")).classes("text-subtitle1 text-bold")
                ui.label(t("agents.bulk_provider.intro")).classes("text-caption")

                with ui.row().classes("w-full items-end"):
                    bulk_provider_select = (
                        ui.select(
                            provider_names,
                            value=current_common_provider,
                            label=t("agents.provider_label"),
                        )
                        .classes("w-48")
                        .mark("agents-bulk-provider")
                    )
                    bulk_provider_select_box[:] = [bulk_provider_select]
                    bulk_include_dataverse = (
                        ui.checkbox(t("agents.bulk_provider.include_dataverse"), value=True).mark(
                            "agents-bulk-include-dataverse"
                        )
                        if dataverse_export_config is not None
                        else None
                    )

                    async def _apply_provider_to_all() -> None:
                        provider_name = bulk_provider_select.value
                        provider = next(
                            (p for p in pipeline_config.providers if p.name == provider_name), None
                        )
                        if not provider_name or provider is None:
                            # The second condition covers a select still
                            # holding a stale value for a provider removed
                            # (in Settings) after this control was rendered
                            # -- without this, the button would otherwise
                            # silently do nothing at all.
                            ui.notify(t("agents.bulk_provider.pick_first"), type="negative")
                            return

                        include_dataverse = (
                            bulk_include_dataverse is not None and bulk_include_dataverse.value
                        )
                        # Written straight into pipeline_config (and the
                        # Dataverse export config), not just the visible
                        # selects -- Settings' remove-provider check reads
                        # pipeline_config.agents directly, so leaving this
                        # queued behind the separate "Save changes" button
                        # (like every other per-agent field here) meant a
                        # provider this bulk action just "switched away
                        # from" still looked in-use there until Save was
                        # also clicked, wrongly blocking its removal.
                        bulk_provider_select.value = provider_name
                        for select in provider_selects.values():
                            select.value = provider_name
                        for agent in pipeline_config.agents:
                            agent.provider = provider_name
                        if include_dataverse and dataverse_provider_select is not None:
                            dataverse_provider_select.value = provider_name
                            if dataverse_export_config is not None:
                                dataverse_export_config.agent.provider = provider_name

                        api_key = _resolve_api_key(provider)
                        try:
                            models = await run.io_bound(fetch_provider_models, provider, api_key)
                        except Exception as exc:  # noqa: BLE001 - surfaced to the user, never fatal
                            logger.warning(
                                "Could not fetch models for provider %s: %s", provider.name, exc
                            )
                            models = None

                        # Re-read through the hoisted containers rather
                        # than the plain local `model_inputs`/
                        # `dataverse_model_input` names this closure
                        # captured at click time -- see this function's
                        # own outer-scope comment for why: a cards.refresh()
                        # during the await above (Save changes / Upload
                        # finishing) would otherwise leave these pointing
                        # at now-orphaned widgets.
                        model_targets = list(model_inputs.values())
                        current_dataverse_model_input = dataverse_model_input_box[0]
                        if include_dataverse and current_dataverse_model_input is not None:
                            model_targets.append(current_dataverse_model_input)

                        agent_count = len(provider_selects) + (1 if include_dataverse else 0)
                        if models:
                            for model_select in model_targets:
                                model_select.set_options(
                                    _model_options(models, model_select.value or "")
                                )
                                model_select.value = models[0]
                            for agent in pipeline_config.agents:
                                agent.model = models[0]
                            if include_dataverse and dataverse_export_config is not None:
                                dataverse_export_config.agent.model = models[0]
                            ui.notify(
                                t(
                                    "agents.bulk_provider.applied",
                                    provider=provider_name,
                                    count=agent_count,
                                ),
                                type="positive",
                            )
                        else:
                            # Blank rather than leaving the OLD provider's
                            # model id in place: a model id is rarely
                            # portable across providers (e.g. OpenRouter's
                            # "~deepseek/..." alias shape doesn't exist on
                            # opencode), so keeping it would silently point
                            # the just-switched agents at a model that
                            # doesn't exist on their new provider instead
                            # of falling back to that provider's own
                            # default -- same "blank means use the
                            # provider's default" contract as leaving the
                            # per-agent Model field empty by hand.
                            for model_select in model_targets:
                                model_select.set_options(_model_options([], ""))
                                model_select.value = ""
                            for agent in pipeline_config.agents:
                                agent.model = None
                            if include_dataverse and dataverse_export_config is not None:
                                dataverse_export_config.agent.model = None
                            ui.notify(
                                t(
                                    "agents.bulk_provider.applied_no_models",
                                    provider=provider_name,
                                    count=agent_count,
                                ),
                                type="warning",
                            )
                        sanitize_all_agents_extra_body(pipeline_config, dataverse_export_config)
                        _persist_overrides(pipeline_config, dataverse_export_config)
                        if on_changed is not None:
                            on_changed()

                    ui.button(
                        t("agents.bulk_provider.apply"), on_click=_apply_provider_to_all
                    ).mark("agents-bulk-provider-apply")

                ui.separator().classes("q-my-sm")
                ui.label(t("agents.bulk_model.intro")).classes("text-caption")

                with ui.row().classes("w-full items-end"):
                    bulk_model_select = (
                        ui.select(
                            [],
                            label=t("agents.model_label"),
                            with_input=True,
                            new_value_mode="add-unique",
                        )
                        .classes("flex-grow")
                        .mark("agents-bulk-model")
                    )

                    async def _refresh_bulk_models() -> None:
                        provider = next(
                            (p for p in pipeline_config.providers if p.name == bulk_provider_select.value),
                            None,
                        )
                        if provider is None:
                            ui.notify(t("agents.pick_provider_first"), type="negative")
                            return
                        await _refresh_models(provider, bulk_model_select)

                    ui.button(icon="refresh", on_click=_refresh_bulk_models).props(
                        "flat round"
                    ).tooltip(t("agents.refresh_models.tooltip")).mark("agents-bulk-model-refresh")

                    bulk_effort_select = (
                        ui.select(
                            {
                                _BULK_EFFORT_KEEP_EXISTING: t("agents.reasoning_effort.keep_existing"),
                                _BULK_EFFORT_INHERIT: t("agents.reasoning_effort.inherit"),
                                "none": "none",
                                "minimal": "minimal",
                                "low": "low",
                                "medium": "medium",
                                "high": "high",
                                "xhigh": "xhigh",
                                "provider_default": "provider_default",
                            },
                            label=t("agents.reasoning_effort_label"),
                            value=_BULK_EFFORT_KEEP_EXISTING,
                        )
                        .classes("w-56")
                        .mark("agents-bulk-effort")
                    )

                    bulk_include_dataverse_model = (
                        ui.checkbox(t("agents.bulk_provider.include_dataverse"), value=True).mark(
                            "agents-bulk-include-dataverse-model"
                        )
                        if dataverse_export_config is not None
                        else None
                    )

                def _apply_model_to_all() -> None:
                    model_value = (bulk_model_select.value or "").strip()
                    if not model_value:
                        ui.notify(t("agents.bulk_model.pick_first"), type="negative")
                        return
                    effort_value = bulk_effort_select.value or _BULK_EFFORT_KEEP_EXISTING
                    touch_effort = effort_value != _BULK_EFFORT_KEEP_EXISTING
                    resolved_effort = (
                        cast(ReasoningEffort, effort_value)
                        if touch_effort and effort_value != _BULK_EFFORT_INHERIT
                        else None
                    )

                    include_dataverse = (
                        bulk_include_dataverse_model is not None
                        and bulk_include_dataverse_model.value
                    )

                    for agent in pipeline_config.agents:
                        agent.model = model_value
                        if touch_effort:
                            agent.reasoning_effort = resolved_effort
                    if include_dataverse and dataverse_export_config is not None:
                        dataverse_export_config.agent.model = model_value
                        if touch_effort:
                            dataverse_export_config.agent.reasoning_effort = resolved_effort

                    agent_count = len(pipeline_config.agents) + (1 if include_dataverse else 0)
                    ui.notify(
                        t("agents.bulk_model.applied", model=model_value, count=agent_count),
                        type="positive",
                    )
                    sanitize_all_agents_extra_body(pipeline_config, dataverse_export_config)
                    _persist_overrides(pipeline_config, dataverse_export_config)
                    # Unlike _apply_provider_to_all above, this makes no
                    # awaited call in between -- a plain refresh is simplest
                    # and correctly re-renders every per-agent card (model
                    # select value, and the Advanced section's resolved
                    # reasoning_effort display) from pipeline_config's own
                    # just-updated state, no risk of orphaning widgets.
                    cards.refresh()
                    if on_changed is not None:
                        on_changed()

                ui.button(t("agents.bulk_model.apply"), on_click=_apply_model_to_all).mark(
                    "agents-bulk-model-apply"
                )

            with ui.card().classes("w-full q-mt-md"):
                ui.label(t("agents.pipeline_behavior.title")).classes("text-subtitle1 text-bold")
                ui.label(t("agents.pipeline_behavior.intro")).classes("text-caption")

                content_fetch_checkbox = (
                    ui.checkbox(
                        t("agents.checkbox.content_fetch"),
                        value=pipeline_config.enable_content_fetch,
                    )
                    .tooltip(t("agents.checkbox.content_fetch.tooltip"))
                    .mark("pipeline-enable-content-fetch")
                )
                doi_resolution_checkbox = (
                    ui.checkbox(
                        t("agents.checkbox.doi_resolution"),
                        value=pipeline_config.enable_doi_resolution,
                    )
                    .tooltip(t("agents.checkbox.doi_resolution.tooltip"))
                    .mark("pipeline-enable-doi-resolution")
                )
                identifier_enrichment_checkbox = (
                    ui.checkbox(
                        t("agents.checkbox.identifier_enrichment"),
                        value=pipeline_config.enable_identifier_enrichment,
                    )
                    .tooltip(t("agents.checkbox.identifier_enrichment.tooltip"))
                    .mark("pipeline-enable-identifier-enrichment")
                )
                validate_pids_checkbox = (
                    ui.checkbox(
                        t("agents.checkbox.validate_pids"),
                        value=pipeline_config.validate_pids,
                    )
                    .tooltip(t("agents.checkbox.validate_pids.tooltip"))
                    .mark("pipeline-validate-pids")
                )
                validate_pids_live_checkbox = (
                    ui.checkbox(
                        t("agents.checkbox.validate_pids_live"),
                        value=pipeline_config.validate_pids_live,
                    )
                    .tooltip(t("agents.checkbox.validate_pids_live.tooltip"))
                    .mark("pipeline-validate-pids-live")
                )
                validate_shacl_conformance_checkbox = (
                    ui.checkbox(
                        t("agents.checkbox.validate_shacl_conformance"),
                        value=pipeline_config.validate_shacl_conformance,
                    )
                    .tooltip(t("agents.checkbox.validate_shacl_conformance.tooltip"))
                    .mark("pipeline-validate-shacl-conformance")
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
                                label=t("agents.provider_label"),
                            )
                            .classes("w-48")
                            .mark(f"agent-provider-{agent.id}")
                        )
                        model_inputs[agent.id] = (
                            ui.select(
                                _model_options([], agent.model or ""),
                                value=agent.model or "",
                                label=t("agents.model_label"),
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
                                ui.notify(t("agents.pick_provider_first"), type="negative")
                                return None
                            return _refresh_models(provider, model_inputs[aid])

                        ui.button(icon="refresh", on_click=_refresh_for_agent).props("flat round").tooltip(
                            t("agents.refresh_models.tooltip")
                        ).mark(f"agent-model-refresh-{agent.id}")
                        temp_inputs[agent.id] = (
                            ui.number(
                                t("agents.temperature_label"),
                                value=agent.temperature,
                                min=0.0,
                                max=2.0,
                                step=0.1,
                            )
                            .classes("w-32")
                            .mark(f"agent-temperature-{agent.id}")
                        )
                        effort_inputs[agent.id] = (
                            ui.select(
                                {
                                    _BULK_EFFORT_INHERIT: t("agents.reasoning_effort.inherit"),
                                    "none": "none",
                                    "minimal": "minimal",
                                    "low": "low",
                                    "medium": "medium",
                                    "high": "high",
                                    "xhigh": "xhigh",
                                    "provider_default": "provider_default",
                                },
                                label=t("agents.reasoning_effort_label"),
                                value=agent.reasoning_effort or _BULK_EFFORT_INHERIT,
                            )
                            .classes("w-56")
                            .mark(f"agent-effort-{agent.id}")
                        )

                    if agent.reasoning_effort is None:
                        # No per-agent override -- but reasoning_effort more
                        # commonly comes from a provider's model_overrides
                        # entry (e.g. config/agents.yaml's own opencode/
                        # muse-spark-1.3-contributor pairing) rather than the
                        # agent itself. Show the resolved value in that case
                        # too, the same cascade create_llm_client actually
                        # uses -- otherwise the select above just reads
                        # "inherit" with no indication of what that resolves
                        # to. Higher effort trades directly for latency on a
                        # reasoning model -- this is also the knob to lower
                        # if a Responses-API model like
                        # muse-spark-1.3-contributor is too slow.
                        resolved_provider = next(
                            (p for p in pipeline_config.providers if p.name == agent.provider),
                            None,
                        )
                        resolved_model = agent.model or ""
                        if (
                            resolved_provider is not None
                            and resolved_model
                            and resolved_provider.effective_api_style(resolved_model)
                            == "responses"
                        ):
                            ui.label(
                                t(
                                    "agents.reasoning_effort",
                                    reasoning_effort=resolved_provider.effective_reasoning_effort(
                                        resolved_model
                                    ),
                                )
                            ).classes("text-caption")

                    with ui.expansion(t("agents.advanced"), icon="tune").classes("w-full q-mt-sm"):
                        deps = ", ".join(agent.depends_on) or t("agents.runs_after.nothing")
                        ui.label(t("agents.runs_after", deps=deps))
                        ui.label(t("agents.produces_fields", fields=", ".join(agent.fields)))
                        if agent.tools:
                            ui.label(t("agents.tools", tools=", ".join(agent.tools)))
                        if agent.extra_body:
                            ui.label(t("agents.extra_body", extra_body=agent.extra_body))
                        ui.label(t("agents.prompt_readonly")).classes("text-caption q-mt-sm")
                        ui.code(agent.prompt, language=None).classes("w-full")

            dataverse_enabled_checkbox = None
            dataverse_provider_select = None
            dataverse_model_input = None
            dataverse_temp_input = None
            dataverse_provider_select_box[0] = None
            dataverse_model_input_box[0] = None
            if dataverse_export_config is not None:
                with ui.card().classes("w-full q-mt-md"):
                    ui.label(t("agents.dataverse.title")).classes("text-subtitle1 text-bold")
                    ui.label(t("agents.dataverse.intro")).classes("text-caption")

                    dataverse_enabled_checkbox = (
                        ui.checkbox(t("agents.dataverse.enabled"), value=dataverse_export_config.enabled)
                        .mark("dataverse-export-enabled")
                    )
                    with ui.row().classes("w-full items-end"):
                        dataverse_provider_select = (
                            ui.select(
                                provider_names,
                                value=dataverse_export_config.agent.provider,
                                label=t("agents.provider_label"),
                            )
                            .classes("w-48")
                            .mark("dataverse-export-provider")
                        )
                        dataverse_provider_select_box[0] = dataverse_provider_select
                        dataverse_model_input = (
                            ui.select(
                                _model_options([], dataverse_export_config.agent.model or ""),
                                value=dataverse_export_config.agent.model or "",
                                label=t("agents.dataverse.model_label"),
                                with_input=True,
                                new_value_mode="add-unique",
                            )
                            .classes("flex-grow")
                            .mark("dataverse-export-model")
                        )
                        _dataverse_model_select = dataverse_model_input
                        dataverse_model_input_box[0] = dataverse_model_input

                        def _refresh_dataverse_models() -> object:
                            provider = next(
                                (p for p in pipeline_config.providers if p.name == dataverse_provider_select.value),
                                None,
                            )
                            if provider is None:
                                ui.notify(t("agents.pick_provider_first"), type="negative")
                                return None
                            return _refresh_models(provider, _dataverse_model_select)

                        ui.button(icon="refresh", on_click=_refresh_dataverse_models).props(
                            "flat round"
                        ).tooltip(t("agents.refresh_models.tooltip")).mark(
                            "dataverse-export-model-refresh"
                        )
                        dataverse_temp_input = (
                            ui.number(
                                t("agents.temperature_label"),
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
                pipeline_config.validate_shacl_conformance = (
                    validate_shacl_conformance_checkbox.value
                )
                for agent in pipeline_config.agents:
                    agent.provider = provider_selects[agent.id].value
                    agent.model = model_inputs[agent.id].value.strip() or None
                    agent.temperature = temp_inputs[agent.id].value
                    effort_value = effort_inputs[agent.id].value or _BULK_EFFORT_INHERIT
                    agent.reasoning_effort = (
                        None
                        if effort_value == _BULK_EFFORT_INHERIT
                        else cast(ReasoningEffort, effort_value)
                    )
                if dataverse_export_config is not None:
                    assert dataverse_enabled_checkbox is not None
                    assert dataverse_provider_select is not None
                    assert dataverse_model_input is not None
                    assert dataverse_temp_input is not None
                    dataverse_export_config.enabled = dataverse_enabled_checkbox.value
                    dataverse_export_config.agent.provider = dataverse_provider_select.value
                    dataverse_export_config.agent.model = dataverse_model_input.value.strip() or None
                    dataverse_export_config.agent.temperature = dataverse_temp_input.value
                sanitize_all_agents_extra_body(pipeline_config, dataverse_export_config)
                _persist_overrides(pipeline_config, dataverse_export_config)
                _warn_model_override_mismatches(pipeline_config, dataverse_export_config)
                ui.notify(t("agents.save.done"), type="positive")
                cards.refresh()
                if on_changed is not None:
                    on_changed()

            ui.button(t("agents.save"), on_click=_save).classes("q-mt-md").mark("agents-save")

        cards()

    return _sync_provider_options


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
        ui.notify(t("agents.upload.rejected", error=exc), type="negative")
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
    # _download() serializes the whole model (model_dump), so a downloaded
    # config always carries every PipelineConfig field -- this per-field
    # copy back must be kept in sync or a field silently reverts to its
    # default on every download/edit/upload round-trip (found missing for
    # validate_shacl_conformance, added when that flag was introduced).
    pipeline_config.validate_shacl_conformance = validated.validate_shacl_conformance

    refresh_cards()
    ui.notify(t("agents.upload.applied", count=len(validated.agents)), type="positive")
