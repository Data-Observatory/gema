"""Click-through tests that don't need a real LLM call — tab navigation
and the Agents tab's JSON download/upload roundtrip. Uses NiceGUI's
in-process user-simulation harness, same as test_app_e2e.py, but these
stay in the fast tier (no @pytest.mark.live) since nothing here touches a
real provider.
"""

from __future__ import annotations

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

    provider_select = user.find(marker="agent-provider-core_metadata")
    provider_select.click()  # opens the dropdown
    user.find("opencode", marker="agent-provider-core_metadata").click()  # picks the option
    user.find(marker="agents-save").click()
    user.find(marker="agents-download").click()

    response = await user.download.next(timeout=5)
    assert response.status_code == 200
    payload = json.loads(response.content)
    agents_by_id = {a["id"]: a for a in payload["agents"]}
    assert agents_by_id["core_metadata"]["provider"] == "opencode"


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


async def test_settings_add_custom_provider(user: User, monkeypatch, tmp_path) -> None:
    """The real default config already declares all 4 pool providers
    (config/agents.yaml), so "Other (custom)" is the only reachable
    choice out of the box — exactly the path a user adding a provider
    the pool doesn't have would take."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
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


async def test_settings_edit_existing_provider_via_picker(user: User, monkeypatch, tmp_path) -> None:
    """Picking an already-configured provider (not just pool/custom ones)
    prefills its real fields and updates it in place on submit, instead of
    being rejected as a duplicate name."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-add-provider-choice")

    choice = user.find(marker="settings-add-provider-choice")
    choice.click()
    user.find("opencode", marker="settings-add-provider-choice").click()

    name_field = list(user.find(marker="settings-add-provider-name").elements)[0]
    url_field = list(user.find(marker="settings-add-provider-url").elements)[0]
    assert name_field.value == "opencode"
    assert url_field.value == "https://opencode.ai/zen/go/v1"

    url_field.value = "https://opencode.example.com/v1"
    user.find(marker="settings-add-provider-submit").click()
    await user.should_see("Updated provider")

    # body.refresh() rebuilds the card with fresh elements — reselect
    # "opencode" and confirm the picker now prefills the *updated* value,
    # proving the edit landed on the live pipeline_config, not a stale copy.
    user.find(marker="settings-add-provider-choice").click()
    user.find("opencode", marker="settings-add-provider-choice").click()
    rebuilt_url_field = list(user.find(marker="settings-add-provider-url").elements)[0]
    assert rebuilt_url_field.value == "https://opencode.example.com/v1"


async def test_settings_add_provider_rejects_duplicate_name(user: User, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-add-provider-choice")

    user.find(marker="settings-add-provider-name").type("zai-coding-plan")  # already exists
    user.find(marker="settings-add-provider-submit").click()

    await user.should_see("already exists")


async def test_settings_tab_lists_key_input_for_every_declared_provider(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression: opencode (declared in config/providers.yaml but not
    used by any agent by default) must still get a key input in Settings
    — otherwise there's no way to ever enter its key before switching an
    agent to it in the Agents tab."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    await user.should_see(marker="settings-input-OPENCODE_API_KEY")
