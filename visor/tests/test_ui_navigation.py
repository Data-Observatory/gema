"""Click-through tests that don't need a real LLM call — tab navigation
and the Agents tab's JSON download/upload roundtrip. Uses NiceGUI's
in-process user-simulation harness, same as test_app_e2e.py, but these
stay in the fast tier (no @pytest.mark.live) since nothing here touches a
real provider.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from nicegui.testing import User

pytestmark = [pytest.mark.asyncio, pytest.mark.nicegui_main_file("visor/app.py")]


async def test_tabs_render_and_are_freely_navigable(user: User, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    await user.should_see(marker="tab-run")
    await user.should_see(marker="run-settings-gate")

    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")

    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-save")

    user.find(marker="tab-run").click()
    await user.should_see(marker="run-settings-gate")


async def test_settings_save_clears_stale_llm_client_cache(user: User, monkeypatch, tmp_path) -> None:
    """create_llm_client()'s cache key is provider+model+temperature+... --
    never the API key's value -- so saving a new key must invalidate
    already-cached clients or the old key silently keeps being used. Fails
    without app.py's reset_client_cache() call in _after_settings_saved."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from metadata_enricher.llm.factory import _client_cache

    _client_cache["fake-provider|fake-model|t=0.0|seed=None|mt=None|c=True|r=True|eb=None"] = object()
    assert _client_cache

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-save").click()

    assert not _client_cache


async def test_agents_tab_json_download_reflects_model_edit(user: User, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-save")

    # Model is a combobox (ui.select with_input=True) — the interaction
    # harness's .type() only supports ui.input/editor/codemirror. A plain
    # `.value = ...` assignment for a value not already in .options gets
    # silently reverted to None by ChoiceElement's own update() (same
    # validation NiceGUI runs on every value change) — set_options(...,
    # value=...) mirrors what the real client does when a user types a
    # new value: add it to options *then* select it.
    model_select = list(user.find(marker="agent-model-core_metadata").elements)[0]
    model_select.set_options([*model_select.options, "test-model-xyz"], value="test-model-xyz")
    user.find(marker="agents-save").click()
    user.find(marker="agents-download").click()

    response = await user.download.next(timeout=5)
    assert response.status_code == 200
    payload = json.loads(response.content)
    agents_by_id = {a["id"]: a for a in payload["agents"]}
    assert agents_by_id["core_metadata"]["model"] == "test-model-xyz"


async def test_agents_tab_provider_is_editable_per_agent(user: User, monkeypatch, tmp_path) -> None:
    """Provider used to be read-only ("Advanced" section); this is the
    other half of resolving the Settings/Agents confusion — an agent's
    provider is set here, not via a global "default provider" picker."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-save")

    # find(text, marker=...) ignores the marker kwarg entirely when a
    # positional text target is given (a real NiceGUI testing-harness
    # quirk) and matches by page-wide text/content instead — it used to
    # accidentally work because "opencode" was unique site-wide, but the
    # Settings tab's merged Providers block now also shows that text (its
    # provider name/URL), so this must target the uniquely-marked select
    # element directly instead of relying on that coincidence.
    provider_select = list(user.find(marker="agent-provider-core_metadata").elements)[0]
    provider_select.value = "opencode"
    user.find(marker="agents-save").click()
    user.find(marker="agents-download").click()

    response = await user.download.next(timeout=5)
    assert response.status_code == 200
    payload = json.loads(response.content)
    agents_by_id = {a["id"]: a for a in payload["agents"]}
    assert agents_by_id["core_metadata"]["provider"] == "opencode"


async def test_agents_tab_refresh_models_populates_combobox(
    user: User, monkeypatch, tmp_path
) -> None:
    """Model has no hardcoded catalog — clicking "Refresh models" fetches
    the real list from the provider's own API (mocked here, real network
    call is model_catalog.fetch_provider_models's job, not this test's)
    and offers it in the combobox."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import visor.pages.agents_page as agents_page_module

    monkeypatch.setattr(
        agents_page_module, "fetch_provider_models", lambda provider, api_key: ["model-a", "model-b"]
    )

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agent-model-refresh-core_metadata")
    user.find(marker="agent-model-refresh-core_metadata").click()

    await user.should_see("Loaded 2 models")
    model_select = list(user.find(marker="agent-model-core_metadata").elements)[0]
    assert "model-a" in model_select.options
    assert "model-b" in model_select.options


async def test_agents_tab_refresh_models_failure_is_non_fatal(user: User, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import visor.pages.agents_page as agents_page_module

    def _boom(provider: object, api_key: object) -> list[str]:
        raise RuntimeError("network is down")

    monkeypatch.setattr(agents_page_module, "fetch_provider_models", _boom)

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agent-model-refresh-core_metadata")
    user.find(marker="agent-model-refresh-core_metadata").click()

    await user.should_see("Could not fetch models")
    # The combobox itself must still work for manual typing after a failure.
    model_select = list(user.find(marker="agent-model-core_metadata").elements)[0]
    model_select.set_options([*model_select.options, "typed-model"], value="typed-model")
    assert model_select.value == "typed-model"


async def test_agents_tab_bulk_provider_switch_applies_to_every_agent(
    user: User, monkeypatch, tmp_path
) -> None:
    """The bulk "switch provider for all agents" control exists precisely
    because switching agents one at a time is how a user ends up with a
    mix of providers and a confusing Run-tab gate (missing_required only
    complains about whichever provider still lacks a key, with no
    indication that a forgotten agent is the reason a second provider is
    even in play). One click must move every agent card (and the
    Dataverse card, since its checkbox defaults to checked) to the chosen
    provider, and auto-pick a fetched model for each."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import visor.pages.agents_page as agents_page_module

    monkeypatch.setattr(
        agents_page_module, "fetch_provider_models", lambda provider, api_key: ["opencode-model-a"]
    )

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-bulk-provider")

    bulk_select = list(user.find(marker="agents-bulk-provider").elements)[0]
    bulk_select.value = "opencode"
    user.find(marker="agents-bulk-provider-apply").click()

    await user.should_see("applied to")

    for agent_id in ("core_metadata", "creators_publishers", "classification", "rights_funding_citations", "media_files"):
        provider_select = list(user.find(marker=f"agent-provider-{agent_id}").elements)[0]
        assert provider_select.value == "opencode"
        model_select = list(user.find(marker=f"agent-model-{agent_id}").elements)[0]
        assert model_select.value == "opencode-model-a"

    dataverse_provider_select = list(user.find(marker="dataverse-export-provider").elements)[0]
    assert dataverse_provider_select.value == "opencode"
    dataverse_model_select = list(user.find(marker="dataverse-export-model").elements)[0]
    assert dataverse_model_select.value == "opencode-model-a"

    # Download WITHOUT clicking "Save changes" first -- bulk apply must
    # commit straight into pipeline_config, not just the visible selects
    # (see the dedicated Settings-tab regression test below for why this
    # matters: a stale pipeline_config is what wrongly blocked removing
    # openrouter after a bulk switch away from it).
    user.find(marker="agents-download").click()
    response = await user.download.next(timeout=5)
    payload = json.loads(response.content)
    assert {a["provider"] for a in payload["agents"]} == {"opencode"}
    assert {a["model"] for a in payload["agents"]} == {"opencode-model-a"}


async def test_agents_tab_bulk_provider_switch_unblocks_removing_old_provider(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression test: bulk-switching every agent away from openrouter to
    opencode, then going straight to the Settings tab (no "Save changes"
    click in between) must let openrouter be removed -- it's no longer
    used by anything. Previously, bulk apply only updated the visible
    selects, leaving pipeline_config.agents (what Settings' remove-check
    actually reads) still pointing at openrouter until Save was also
    clicked, so removal was wrongly refused."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import visor.pages.agents_page as agents_page_module

    monkeypatch.setattr(
        agents_page_module, "fetch_provider_models", lambda provider, api_key: ["opencode-model-a"]
    )

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-bulk-provider")

    bulk_select = list(user.find(marker="agents-bulk-provider").elements)[0]
    bulk_select.value = "opencode"
    user.find(marker="agents-bulk-provider-apply").click()
    await user.should_see("applied to")

    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-provider-remove-openrouter")
    user.find(marker="settings-provider-remove-openrouter").click()
    await user.should_see("Removed provider 'openrouter'")


async def test_removing_the_default_provider_keeps_config_re_uploadable(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression test: PipelineConfig.default_provider is cross-validated
    against providers on reconstruction (PipelineConfig._validate_
    references) even though it's never read for routing -- removing a
    provider that also happens to be default_provider (exactly what the
    previous test's own flow sets up: bulk-switch away from openrouter,
    then remove it) must not leave that field dangling, or the app's own
    documented backup workflow (Download configuration -> hand-edit ->
    Upload) would reject the user's own, currently-valid config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import visor.pages.agents_page as agents_page_module
    from metadata_enricher.config.models import PipelineConfig

    monkeypatch.setattr(
        agents_page_module, "fetch_provider_models", lambda provider, api_key: ["opencode-model-a"]
    )

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-bulk-provider")
    bulk_select = list(user.find(marker="agents-bulk-provider").elements)[0]
    bulk_select.value = "opencode"
    user.find(marker="agents-bulk-provider-apply").click()
    await user.should_see("applied to")

    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-provider-remove-openrouter")
    user.find(marker="settings-provider-remove-openrouter").click()
    await user.should_see("Removed provider 'openrouter'")

    user.find(marker="tab-agents").click()
    user.find(marker="agents-download").click()
    response = await user.download.next(timeout=5)
    payload = json.loads(response.content)
    assert payload["default_provider"] != "openrouter"

    # The exact reconstruction _handle_upload() runs on a re-upload
    # (PipelineConfig's own cross-field validator, which is what raised
    # on a dangling default_provider before the fix) -- proves the
    # downloaded config is genuinely re-uploadable, not just that the
    # field's value looks different above.
    PipelineConfig(**payload)


async def test_removing_a_now_unused_provider_preserves_its_saved_key(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression test: _save()'s env dict used to be rebuilt from only
    the currently-rendered key inputs, so removing a provider (which
    re-renders Settings without that provider's input field) and then
    clicking Save & Continue for any unrelated reason silently deleted
    its previously-saved key from settings.json -- reachable in far fewer
    steps now that the Agents tab's bulk switch makes a provider unused
    in one click. The key must survive on disk even after its provider
    is removed, so switching an agent back to it later doesn't
    unnecessarily re-gate the Run tab."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import visor.pages.agents_page as agents_page_module
    from visor.settings import load_settings

    monkeypatch.setattr(
        agents_page_module, "fetch_provider_models", lambda provider, api_key: ["opencode-model-a"]
    )

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-provider-edit-openrouter")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("keep-me-please")
    user.find(marker="settings-save").click()
    await user.should_see("Settings saved")

    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-bulk-provider")
    bulk_select = list(user.find(marker="agents-bulk-provider").elements)[0]
    bulk_select.value = "opencode"
    user.find(marker="agents-bulk-provider-apply").click()
    await user.should_see("applied to")

    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-provider-remove-openrouter")
    user.find(marker="settings-provider-remove-openrouter").click()
    await user.should_see("Removed provider 'openrouter'")

    # Save & Continue for an unrelated reason (e.g. the OPENCODE_API_KEY
    # this bulk switch now requires) -- must not touch the already-saved,
    # now-unrendered OPENROUTER_API_KEY entry.
    user.find(marker="settings-provider-edit-opencode").click()
    await user.should_see(marker="settings-input-OPENCODE_API_KEY")
    user.find(marker="settings-input-OPENCODE_API_KEY").type("opencode-key")
    user.find(marker="settings-save").click()
    await user.should_see("Settings saved")

    saved = load_settings()
    assert saved.env.get("OPENROUTER_API_KEY") == "keep-me-please"
    assert saved.env.get("OPENCODE_API_KEY") == "opencode-key"


async def test_agents_upload_changing_providers_keeps_settings_savable(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression test: Settings' cross-tab broadcast listener only
    patches existing rows' caption text -- it can't add or remove a row.
    An Agents-tab config upload that changes the provider list must
    therefore fall back to a full Settings rebuild, or Save & Continue
    (which indexes its inputs by every *current* provider name) would
    raise KeyError the moment it's clicked with Settings still showing
    the stale, pre-upload row set."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from nicegui.elements.upload_files import SmallFileUpload

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-download")
    user.find(marker="agents-download").click()
    response = await user.download.next(timeout=5)
    payload = json.loads(response.content)
    payload["providers"].append(
        {"name": "groq", "api_key_env": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1"}
    )

    upload_element = list(user.find(marker="agents-upload").elements)[0]
    await upload_element.handle_uploads(
        [
            SmallFileUpload(
                name="roundtrip.json",
                content_type="application/json",
                _data=json.dumps(payload).encode("utf-8"),
            )
        ]
    )
    await user.should_see("Applied uploaded configuration")

    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-provider-edit-groq")
    user.find(marker="settings-save").click()
    await user.should_see("Settings saved")


async def test_run_form_typing_survives_unrelated_agents_tab_save(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression guard for the cross-tab broadcast wiring itself: an
    Agents-tab Save that doesn't touch any provider assignment must not
    blow away in-progress typing on the Run form. _render_form_phase
    builds plain, unbound ui.input widgets, so a naive "refresh the Run
    tab on every broadcast" would silently discard this -- the gate is
    only supposed to rebuild when its own missing-key shape changes."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-input-url")
    user.find(marker="run-input-url").type("https://example.org/still-here")

    user.find(marker="tab-agents").click()
    await user.should_see(marker="pipeline-enable-content-fetch")
    checkbox = list(user.find(marker="pipeline-enable-content-fetch").elements)[0]
    checkbox.value = not checkbox.value
    user.find(marker="agents-save").click()
    await user.should_see("updated for this session")

    user.find(marker="tab-run").click()
    url_input = list(user.find(marker="run-input-url").elements)[0]
    assert url_input.value == "https://example.org/still-here"


async def test_agents_tab_unsaved_temperature_survives_bulk_provider_switch(
    user: User, monkeypatch, tmp_path
) -> None:
    """The bulk provider switch commits provider/model straight into
    pipeline_config (see the earlier fix for why) and then broadcasts to
    every tab, including this one -- Agents' own broadcast listener
    (_sync_provider_options) must not be a full cards.refresh(), or that
    broadcast would immediately erase a not-yet-saved edit sitting on a
    completely unrelated agent card, the moment "Apply to all" is
    clicked for a different agent's provider."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import visor.pages.agents_page as agents_page_module

    monkeypatch.setattr(
        agents_page_module, "fetch_provider_models", lambda provider, api_key: ["opencode-model-a"]
    )

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agent-temperature-core_metadata")

    temp_input = list(user.find(marker="agent-temperature-core_metadata").elements)[0]
    temp_input.value = 1.5

    bulk_select = list(user.find(marker="agents-bulk-provider").elements)[0]
    bulk_select.value = "opencode"
    user.find(marker="agents-bulk-provider-apply").click()
    await user.should_see("applied to")

    temp_input_after = list(user.find(marker="agent-temperature-core_metadata").elements)[0]
    assert temp_input_after.value == 1.5


async def test_agents_tab_unsaved_temperature_survives_settings_add_provider(
    user: User, monkeypatch, tmp_path
) -> None:
    """Same guarantee from the other direction: adding a provider in
    Settings broadcasts to Agents too, and must only refresh provider
    *options* (a newly-added provider becomes selectable) without
    touching any agent's current model/temperature field."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agent-temperature-core_metadata")
    temp_input = list(user.find(marker="agent-temperature-core_metadata").elements)[0]
    temp_input.value = 1.5

    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-add-provider-toggle")
    user.find(marker="settings-add-provider-toggle").click()
    await user.should_see(marker="settings-add-provider-choice")
    user.find(marker="settings-add-provider-name").type("groq")
    user.find(marker="settings-add-provider-submit").click()
    await user.should_see("Added provider 'groq'")

    user.find(marker="tab-agents").click()
    temp_input_after = list(user.find(marker="agent-temperature-core_metadata").elements)[0]
    assert temp_input_after.value == 1.5
    provider_select = list(user.find(marker="agent-provider-core_metadata").elements)[0]
    assert "groq" in provider_select.options


async def test_settings_unsaved_key_survives_unrelated_agents_tab_save(
    user: User, monkeypatch, tmp_path
) -> None:
    """The other half of the cross-tab broadcast safety guarantee: a
    Settings edit panel can be open with a typed-but-unsaved API key, and
    an Agents-tab Save (which broadcasts too) must not collapse it back
    to empty. This is why Settings' broadcast listener only patches each
    provider's "used by" caption text in place instead of rebuilding the
    whole body."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-provider-edit-openrouter")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("not-yet-saved-key")

    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-save")
    user.find(marker="agents-save").click()
    await user.should_see("updated for this session")

    user.find(marker="tab-settings").click()
    key_input = list(user.find(marker="settings-input-OPENROUTER_API_KEY").elements)[0]
    assert key_input.value == "not-yet-saved-key"


async def test_run_tab_gate_reflects_bulk_provider_switch_without_visiting_settings(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression test: the Run tab's gate is rendered once at page load
    (tab_panels mount every tab up front and never re-render it on a
    plain tab switch) and previously only ever got refreshed after a
    Settings save. Bulk-switching every agent to opencode (no
    OPENCODE_API_KEY set) must update the gate to ask for opencode's key,
    not keep showing the original openrouter one -- broadcasting from the
    Agents tab, not just Settings, is what this test guards."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import visor.pages.agents_page as agents_page_module

    monkeypatch.setattr(
        agents_page_module, "fetch_provider_models", lambda provider, api_key: ["opencode-model-a"]
    )

    await user.open("/")
    await user.should_see(marker="run-settings-gate")
    await user.should_see("openrouter")

    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-bulk-provider")
    bulk_select = list(user.find(marker="agents-bulk-provider").elements)[0]
    bulk_select.value = "opencode"
    user.find(marker="agents-bulk-provider-apply").click()
    await user.should_see("applied to")

    user.find(marker="tab-run").click()
    await user.should_see(marker="run-settings-gate")
    await user.should_see("OPENCODE_API_KEY")


async def test_agents_tab_bulk_provider_switch_without_dataverse(
    user: User, monkeypatch, tmp_path
) -> None:
    """Unchecking "also include the Dataverse classifier" must leave that
    card's own provider/model untouched."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import visor.pages.agents_page as agents_page_module

    monkeypatch.setattr(
        agents_page_module, "fetch_provider_models", lambda provider, api_key: ["opencode-model-a"]
    )

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-bulk-include-dataverse")

    dataverse_provider_before = list(user.find(marker="dataverse-export-provider").elements)[0].value

    bulk_select = list(user.find(marker="agents-bulk-provider").elements)[0]
    bulk_select.value = "opencode"
    include_checkbox = list(user.find(marker="agents-bulk-include-dataverse").elements)[0]
    include_checkbox.value = False
    user.find(marker="agents-bulk-provider-apply").click()

    await user.should_see("applied to")

    provider_select = list(user.find(marker="agent-provider-core_metadata").elements)[0]
    assert provider_select.value == "opencode"
    dataverse_provider_select = list(user.find(marker="dataverse-export-provider").elements)[0]
    assert dataverse_provider_select.value == dataverse_provider_before


async def test_agents_tab_bulk_provider_switch_fetch_failure_is_non_fatal(
    user: User, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import visor.pages.agents_page as agents_page_module

    def _boom(provider: object, api_key: object) -> list[str]:
        raise RuntimeError("network is down")

    monkeypatch.setattr(agents_page_module, "fetch_provider_models", _boom)

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-bulk-provider")

    bulk_select = list(user.find(marker="agents-bulk-provider").elements)[0]
    bulk_select.value = "opencode"
    user.find(marker="agents-bulk-provider-apply").click()

    await user.should_see("but its model")
    # Provider switch itself must still have gone through despite the
    # model fetch failing.
    provider_select = list(user.find(marker="agent-provider-core_metadata").elements)[0]
    assert provider_select.value == "opencode"


async def test_agents_tab_bulk_provider_switch_model_survives_concurrent_save(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression test for the race render_agents()'s outer-scope
    provider_selects/model_inputs hoisting exists to close: "Apply to
    all" is async and only writes the fetched model into widgets *after*
    the /models call returns. If "Save changes" is clicked while that
    call is still in flight, its own cards.refresh() tears down and
    rebuilds every widget -- the fetched model must still land on the
    resulting, now-current widgets (and in pipeline_config) instead of
    silently applying to orphaned, pre-refresh ones."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import threading

    import visor.pages.agents_page as agents_page_module

    release = threading.Event()

    def _slow_fetch(provider: object, api_key: object) -> list[str]:
        release.wait(timeout=5)
        return ["opencode-model-a"]

    monkeypatch.setattr(agents_page_module, "fetch_provider_models", _slow_fetch)

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-bulk-provider")

    bulk_select = list(user.find(marker="agents-bulk-provider").elements)[0]
    bulk_select.value = "opencode"
    user.find(marker="agents-bulk-provider-apply").click()
    await asyncio.sleep(0.1)  # let the click's coroutine reach the in-flight fetch

    # "Save changes" while the fetch is still pending -- rebuilds every
    # card via cards.refresh(), exactly what used to orphan model_inputs.
    user.find(marker="agents-save").click()
    await asyncio.sleep(0.1)

    release.set()
    await user.should_see("applied to")

    model_select = list(user.find(marker="agent-model-core_metadata").elements)[0]
    assert model_select.value == "opencode-model-a"


async def test_agents_tab_dataverse_export_card_saves_toggle_and_model(
    user: User, monkeypatch, tmp_path
) -> None:
    """The Dataverse Export card has no download button of its own (it's
    not part of pipeline_config) — verify persistence the same way Save
    itself proves it: it refreshes the card, which rebuilds from
    whatever's actually stored in the export config object. If Save had
    written to the wrong object, the rebuilt checkbox would show the
    stale (pre-edit) value instead of the one just saved."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="dataverse-export-enabled")

    user.find(marker="dataverse-export-enabled").click()  # config/dataverse_export.yaml ships enabled: true
    dataverse_model_select = list(user.find(marker="dataverse-export-model").elements)[0]
    dataverse_model_select.set_options(
        [*dataverse_model_select.options, "test-fast-model"], value="test-fast-model"
    )
    user.find(marker="agents-save").click()

    rebuilt_checkbox = list(user.find(marker="dataverse-export-enabled").elements)[0]
    rebuilt_model = list(user.find(marker="dataverse-export-model").elements)[0]
    assert rebuilt_checkbox.value is False
    assert rebuilt_model.value == "test-fast-model"


async def test_agents_tab_advanced_shows_tools_and_extra_body(
    user: User, monkeypatch, tmp_path
) -> None:
    """creators_publishers is the one agent configured with
    tools: [lookup_organization] in the real config/agents.yaml; every
    agent sets extra_body (disabling deepseek's default reasoning mode,
    required alongside Instructor's forced tool_choice). Both must be
    visible in the read-only Advanced section for transparency -- same
    treatment already given to depends_on/fields.

    load_pipeline_config() rewrites config/agents.yaml's opencode/
    thinking-shaped extra_body to visor's openrouter/reasoning-shaped
    default before the app ever sees it (see bootstrap.py's
    apply_external_user_provider_overrides) -- assert on that shape, not
    the on-disk file's."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-save")

    await user.should_see("Tools: lookup_organization")
    await user.should_see("Extra request options:")
    await user.should_see("reasoning")


async def test_agents_tab_pipeline_behavior_toggles_persist(
    user: User, monkeypatch, tmp_path
) -> None:
    """Pipeline-wide toggles (enable_content_fetch, enable_doi_resolution,
    ...) used to be reachable only by hand-editing the downloaded JSON and
    re-uploading it -- and re-uploading didn't even round-trip 2 of them
    (see test_agents_page.py). Flip two here directly and confirm Save +
    Download reflects both."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="pipeline-enable-content-fetch")

    content_fetch_checkbox = list(user.find(marker="pipeline-enable-content-fetch").elements)[0]
    assert content_fetch_checkbox.value is True  # config/agents.yaml ships enable_content_fetch: true
    content_fetch_checkbox.value = False

    doi_checkbox = list(user.find(marker="pipeline-enable-doi-resolution").elements)[0]
    assert doi_checkbox.value is False  # config/agents.yaml never sets this -- model default
    doi_checkbox.value = True

    user.find(marker="agents-save").click()
    user.find(marker="agents-download").click()

    response = await user.download.next(timeout=5)
    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["enable_content_fetch"] is False
    assert payload["enable_doi_resolution"] is True


async def test_run_form_shows_fetched_content_auto_fetch_hint(
    user: User, monkeypatch, tmp_path
) -> None:
    """The manual "Fetched content" field predates enable_content_fetch
    (now on by default in config/agents.yaml) -- without this hint a user
    could think they must paste HTML by hand, when the pipeline already
    fetches the page itself whenever the flag is on and this is left
    blank."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    # visor's default is openrouter (see bootstrap.py's
    # apply_external_user_provider_overrides), not config/agents.yaml's
    # on-disk opencode -- that's the key the Run tab's gate actually asks
    # for.
    user.find(marker="settings-provider-edit-openrouter").click()  # reveal its key input
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-input-fetched_content")
    await user.should_see("leave blank to let the pipeline fetch")


async def test_run_form_has_context_hints_field(user: User, monkeypatch, tmp_path) -> None:
    """context_hints (commit 407f3da) is a real, still-live convention --
    config/agents.yaml's shared system_prompt treats a "context_hints" input
    key as externally pre-verified evidence, trusted like the resource's own
    content unless the resource's own text contradicts it. ResourceDescription
    passes it through automatically (extra="allow"), but the Run form never
    exposed a field for it -- a user had no way to give the agents this kind
    of free-text clue (publish year, file count, authors, etc.) without
    switching to Paste JSON."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-input-context_hints")
    await user.should_see("Context hints (optional)")
    await user.should_see("externally verified")

    hints_input = list(user.find(marker="run-input-context_hints").elements)[0]
    assert "published in" in hints_input._props.get("placeholder", "").lower()


async def test_result_phase_shows_models_used(user: User, monkeypatch, tmp_path) -> None:
    """A user relying on an auto-updating alias (e.g. OpenRouter's
    "~deepseek/deepseek-v4-flash-latest") wants to confirm the real,
    resolved version it actually served -- PipelineResult.models_used
    carries that per-agent, so the Result phase should show it. Monkeypatch
    run_single (not a real LLM call) so this stays in the fast, non-live
    tier -- same technique as test_agents_page.py's fakes."""
    from metadata_enricher.pipeline import PipelineResult
    from metadata_enricher.types import MetadataDocument, ResourceDescription, TokenUsage

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    fake_result = PipelineResult(
        resource=ResourceDescription(url="https://example.org/x"),
        document=MetadataDocument(fields={"titles": []}),
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        models_used={"core_metadata": "deepseek/deepseek-v4-flash-2508"},
    )
    monkeypatch.setattr("visor.pages.run_page.run_single", lambda *a, **kw: fake_result)

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-input-url")
    user.find(marker="run-input-url").type("https://example.org/x")
    user.find(marker="run-submit").click()

    await user.should_see(marker="result-success")
    await user.should_see(marker="result-models-used")
    await user.should_see("core_metadata")
    await user.should_see("deepseek/deepseek-v4-flash-2508")


async def test_result_phase_shows_elapsed_time(user: User, monkeypatch, tmp_path) -> None:
    """The result phase should report how long the run actually took, using
    the same wall-clock span the running phase's live "Elapsed" label was
    counting up."""
    from metadata_enricher.pipeline import PipelineResult
    from metadata_enricher.types import MetadataDocument, ResourceDescription

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    fake_result = PipelineResult(
        resource=ResourceDescription(url="https://example.org/x"),
        document=MetadataDocument(fields={"titles": []}),
    )
    monkeypatch.setattr("visor.pages.run_page.run_single", lambda *a, **kw: fake_result)

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-input-url")
    user.find(marker="run-input-url").type("https://example.org/x")
    user.find(marker="run-submit").click()

    await user.should_see(marker="result-success")
    await user.should_see(marker="result-elapsed")
    elapsed_label = list(user.find(marker="result-elapsed").elements)[0]
    assert elapsed_label.text.startswith("Completed in ")


async def test_run_form_clear_cache_button_purges_response_cache(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression: re-submitting the same resource used to always replay a
    cached LLM response with no way to force a fresh call short of waiting
    out the 7-day TTL or restarting visor. The Clear cache button on the Run
    tab must call the real cache-purge function, not just reset the
    in-memory client cache (see clear_response_cache's docstring for why
    those are different)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    calls = []
    monkeypatch.setattr("visor.pages.run_page.clear_response_cache", lambda: calls.append(True))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-clear-cache")
    user.find(marker="run-clear-cache").click()

    assert calls == [True]
    await user.should_see("Cache cleared")


async def test_result_phase_shows_real_error_not_unknown(user: User, monkeypatch, tmp_path) -> None:
    """Regression: a resource that fails without run_single() raising (e.g.
    every agent's provider call rejected an invalid API key) returns a
    PipelineResult with .error set and .success False -- it doesn't raise.
    _execute()'s except block used to be the only place state.error was
    ever set, so this path left state.error at its default None and the
    failure UI always showed the generic "Unknown error" fallback instead
    of the real reason. Also checks the auth-error message gets rewritten
    into something actionable instead of the raw provider text."""
    from metadata_enricher.pipeline import PipelineResult
    from metadata_enricher.types import ResourceDescription

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    fake_result = PipelineResult(
        resource=ResourceDescription(url="https://example.org/x"),
        error="All agents failed: Error code: 401 - No auth credentials found",
    )
    monkeypatch.setattr("visor.pages.run_page.run_single", lambda *a, **kw: fake_result)

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-input-url")
    user.find(marker="run-input-url").type("https://example.org/x")
    user.find(marker="run-submit").click()

    await user.should_see(marker="result-failure")
    await user.should_see(marker="result-error")
    error_label = list(user.find(marker="result-error").elements)[0]
    assert "Unknown error" not in error_label.text
    assert "API key for this provider was rejected" in error_label.text
    assert "Check it in Settings" in error_label.text


async def test_run_form_fields_have_example_placeholders(user: User, monkeypatch, tmp_path) -> None:
    """Empty inputs give no clue what format is expected -- a placeholder
    (grayed hint text, not a prefilled value the user has to remember to
    clear) fixes that for every form field, not just the ones with a
    separate caption underneath."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-input-url")
    url_input = list(user.find(marker="run-input-url").elements)[0]
    assert url_input._props.get("placeholder")
    doi_input = list(user.find(marker="run-input-doi").elements)[0]
    assert doi_input._props.get("placeholder")


async def test_run_form_has_doi_field_and_marks_optional_fields(
    user: User, monkeypatch, tmp_path
) -> None:
    """doi is a real ResourceDescription field (like url/title/description/
    fetched_content) but was missing from the Run tab's form entirely -- a
    user with a DOI already in hand had no way to enter it without
    switching to Paste JSON. Also: url/title/description are the only
    fields where at least one is required (see the "Fill at least url,
    title, or description" check in _run()); doi/publisher/frequency/
    fetched_content are all purely optional and should say so."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-input-doi")
    await user.should_see("DOI (optional)")
    await user.should_see("Publisher (optional)")
    await user.should_see("Frequency (optional)")


async def test_settings_add_custom_provider(user: User, monkeypatch, tmp_path) -> None:
    """The real default config already declares all 5 pool providers
    (config/agents.yaml), so "Other (custom)" is the only reachable
    choice out of the box — exactly the path a user adding a provider
    the pool doesn't have would take."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-add-provider-toggle")
    user.find(marker="settings-add-provider-toggle").click()
    await user.should_see(marker="settings-add-provider-choice")

    user.find(marker="settings-add-provider-name").type("groq")
    user.find(marker="settings-add-provider-url").type("https://api.groq.com/openai/v1")
    user.find(marker="settings-add-provider-env-name").type("GROQ_API_KEY")
    user.find(marker="settings-add-provider-key").type("test-groq-key")
    user.find(marker="settings-add-provider-submit").click()

    await user.should_see(marker="settings-input-GROQ_API_KEY")
    # The typed key pre-fills the new input so the user isn't asked twice.
    new_key_input = list(user.find(marker="settings-input-GROQ_API_KEY").elements)[0]
    assert new_key_input.value == "test-groq-key"


# The pool-autofill logic (which entries are offered, name/URL/env-name
# mapping) is unit-tested directly in test_settings.py's
# TestAddableProviders — booting the whole app can't exercise "a pool
# entry that isn't already added" since config/agents.yaml's real
# providers list already covers every pool entry (see the test above),
# and the relevant module-level state is computed during the `user`
# fixture's own setup, before any test-body monkeypatch could intercept it.


async def test_settings_edit_existing_provider_base_url(user: User, monkeypatch, tmp_path) -> None:
    """Providers and their keys are one merged block — an already-configured
    provider's Base URL is directly editable in its own row (no separate
    picker step needed), and Save & Continue persists it in place."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-provider-edit-opencode")
    user.find(marker="settings-provider-edit-opencode").click()  # reveal its row
    await user.should_see(marker="settings-provider-url-opencode")

    url_field = list(user.find(marker="settings-provider-url-opencode").elements)[0]
    assert url_field.value == "https://opencode.ai/zen/go/v1"
    url_field.value = "https://opencode.example.com/v1"
    user.find(marker="settings-save").click()

    # ui.refreshable.refresh(), called inside _save(), is unawaited there
    # (fire-and-forget) — it schedules a background asyncio task rather
    # than rebuilding inline, and only actually runs once the event loop
    # gets a tick. await user.should_see(...) does NOT reliably provide
    # that tick: its retry loop only sleeps if the target isn't already
    # found on the very first (synchronous) check, and "settings-save" is
    # trivially already present. An explicit sleep is needed here, or the
    # next find() below would still see the pre-refresh element (same id,
    # edit panel still open from earlier in this test) and clicking
    # "edit" again would wrongly toggle it back closed.
    await asyncio.sleep(0.1)

    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-provider-edit-opencode")
    user.find(marker="settings-provider-edit-opencode").click()  # rebuilt row starts collapsed again
    await user.should_see(marker="settings-provider-url-opencode")
    rebuilt_url_field = list(user.find(marker="settings-provider-url-opencode").elements)[0]
    assert rebuilt_url_field.value == "https://opencode.example.com/v1"


async def test_settings_save_nudges_towards_unassigned_key(user: User, monkeypatch, tmp_path) -> None:
    """Closing the loop from the other direction of the Agents tab's own
    "used by: ..." hint: saving a key for a provider no agent (or the
    Dataverse classifier) is actually assigned to is a likely papercut
    -- the user probably meant to also switch an agent to it -- so
    Settings nudges towards the Agents tab instead of silently accepting
    a key that will never be read."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    # openai is genuinely unused (see test_settings_remove_unused_provider
    # for why), making it the key that should trigger the nudge here.
    await user.should_see(marker="settings-provider-edit-openai")
    user.find(marker="settings-provider-edit-openai").click()
    await user.should_see(marker="settings-input-OPENAI_API_KEY")
    user.find(marker="settings-input-OPENAI_API_KEY").type("sk-unused-key")
    user.find(marker="settings-save").click()

    await user.should_see("openai")
    await user.should_see("no agent uses it yet")


async def test_settings_save_without_unassigned_keys_skips_the_nudge(
    user: User, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-provider-edit-openrouter")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("sk-used-key")
    user.find(marker="settings-save").click()

    await user.should_see("Settings saved")
    await user.should_not_see("no agent uses it yet")


async def test_settings_remove_unused_provider(user: User, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    # openai is genuinely unused: visor's live default (see bootstrap.py's
    # apply_external_user_provider_overrides) runs every agent -- the 5
    # main ones and dataverse export's Subject Classifier alike -- on
    # openrouter, leaving opencode unused here too, not just openai.
    await user.should_see(marker="settings-provider-remove-openai")

    user.find(marker="settings-provider-remove-openai").click()

    await user.should_see("Removed provider 'openai'")


async def test_settings_remove_provider_in_use_is_blocked(user: User, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    # openrouter is visor's actual default (see bootstrap.py's
    # apply_external_user_provider_overrides) -- every agent uses it here,
    # even though config/agents.yaml's on-disk default_provider is
    # opencode, so removing it must be refused.
    await user.should_see(marker="settings-provider-remove-openrouter")

    user.find(marker="settings-provider-remove-openrouter").click()

    await user.should_see("Can't remove 'openrouter'")
    await user.should_see(marker="settings-provider-remove-openrouter")  # still there


async def test_settings_add_provider_rejects_duplicate_name(user: User, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-add-provider-toggle")
    user.find(marker="settings-add-provider-toggle").click()
    await user.should_see(marker="settings-add-provider-choice")

    user.find(marker="settings-add-provider-name").type("zai-coding-plan")  # already exists
    user.find(marker="settings-add-provider-submit").click()

    await user.should_see("already exists")


async def test_settings_save_shows_edited_key_not_stale_value(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression: editing a provider's key and saving must not visually
    revert to the pre-edit value. _save() used to refresh the Settings body
    from the `current` VisorSettings captured at page load, which was never
    updated after a save -- so the very next redraw of this tab (even
    without navigating away) showed the old key again, though the correct
    one was already on disk."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-opencode").click()
    await user.should_see(marker="settings-input-OPENCODE_API_KEY")

    user.find(marker="settings-input-OPENCODE_API_KEY").type("first-key")
    user.find(marker="settings-save").click()
    # See test_settings_edit_existing_provider_base_url's comment: refresh()
    # is unawaited fire-and-forget, needs an explicit tick before the next
    # find() below would otherwise still see the pre-refresh element.
    await asyncio.sleep(0.1)

    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-provider-edit-opencode")
    user.find(marker="settings-provider-edit-opencode").click()
    await user.should_see(marker="settings-input-OPENCODE_API_KEY")
    key_input = list(user.find(marker="settings-input-OPENCODE_API_KEY").elements)[0]
    assert key_input.value == "first-key"


async def test_settings_tab_lists_key_input_for_every_declared_provider(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression: every provider declared in config/agents.yaml's
    providers: list must get a key input in Settings, whether or not any
    agent currently uses it — otherwise there's no way to ever enter its
    key before switching an agent to it in the Agents tab."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    await user.should_see(marker="settings-provider-edit-opencode")
    user.find(marker="settings-provider-edit-opencode").click()  # reveal its row
    await user.should_see(marker="settings-input-OPENCODE_API_KEY")
