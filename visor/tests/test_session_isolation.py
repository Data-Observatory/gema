"""Multi-connection hosted-mode regression.

visor is normally a single-user pywebview window, but it can also be hosted
(``VISOR_NATIVE=0``) so several people connect to the *same running
process* over the network. ``main_page()`` used to alias the module-level
``PipelineConfig`` / ``DataverseExportConfig`` instead of copying them, so
one session's *not-yet-saved* Agents-tab edit (provider/model/temperature,
mutated in place — see agents_page.py's module docstring) leaked into
every other session's live in-memory objects before either side ever
clicked Save. Each session's in-progress edit is meant to stay private to
it until committed.

A *saved* Agents-tab edit is a different story since visor/settings.py
gained agent_overrides (see its apply_agent_overrides() docstring): Save
now persists provider/model/temperature/dataverse/pipeline-toggle choices
the same way Settings' API keys always have -- one shared settings.json
in native mode (by design: native mode is one desktop user, so a second
connection legitimately picking up what was just saved is the whole
point, not a leak), one isolated per-browser store in hosted mode (see
session_settings.py). So a *saved* native-mode edit is expected to appear
in a freshly opened second connection below; only an *unsaved* one must
not.

Settings (API keys) had the same aliasing-vs-persistence distinction from
a different cause: unlike PipelineConfig, VisorSettings was never
in-memory per-session state to begin with — every session read from and
wrote to the one shared settings.json file. See visor/session_settings.py
for the fix and its documented residual limitation.

Uses the same in-process ``nicegui.testing.User`` harness as
test_ui_navigation.py / test_app_e2e.py, plus the ``create_user`` fixture
(undocumented here, but shipped by nicegui.testing.user_plugin) to open a
second, independent session against the same already-running simulated
app -- exactly the "second browser tab" this bug is about.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from nicegui.testing import User

pytestmark = [pytest.mark.asyncio, pytest.mark.nicegui_main_file("visor/app.py")]


async def test_unsaved_agent_edit_does_not_leak_across_sessions(
    user: User, create_user: Callable[[], User], monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-save")

    provider_select = list(user.find(marker="agent-provider-core_metadata").elements)[0]
    original_provider = provider_select.value
    assert original_provider != "opencode"  # otherwise this test can't prove anything
    provider_select.value = "opencode"
    # Deliberately never click agents-save -- this edit must stay
    # session-local until committed.

    # A fresh session on the same running app -- without the deep-copy fix
    # this sees session A's mutated shared PipelineConfig object instead of
    # a clean copy of the one loaded at module import time, even though
    # session A never saved anything.
    user_b = create_user()
    await user_b.open("/")
    user_b.find(marker="tab-agents").click()
    await user_b.should_see(marker="agents-save")
    user_b.find(marker="agents-download").click()

    response_b = await user_b.download.next(timeout=5)
    agents_by_id_b = {a["id"]: a for a in json.loads(response_b.content)["agents"]}
    assert agents_by_id_b["core_metadata"]["provider"] == original_provider


async def test_saved_agent_edit_propagates_to_a_fresh_native_session(
    user: User, create_user: Callable[[], User], monkeypatch, tmp_path
) -> None:
    """The intended counterpart to the unsaved case above: once Save is
    clicked, visor/settings.py's agent_overrides make the choice durable
    (survives an app relaunch) by writing it to the one native-mode
    settings.json -- so a second connection picking it up on its own next
    page load is correct, not a leak. See this module's docstring."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-save")

    provider_select = list(user.find(marker="agent-provider-core_metadata").elements)[0]
    original_provider = provider_select.value
    assert original_provider != "opencode"  # otherwise this test can't prove anything
    provider_select.value = "opencode"
    user.find(marker="agents-save").click()
    user.find(marker="agents-download").click()

    response_a = await user.download.next(timeout=5)
    agents_by_id_a = {a["id"]: a for a in json.loads(response_a.content)["agents"]}
    assert agents_by_id_a["core_metadata"]["provider"] == "opencode"

    user_b = create_user()
    await user_b.open("/")
    user_b.find(marker="tab-agents").click()
    await user_b.should_see(marker="agents-save")
    user_b.find(marker="agents-download").click()

    response_b = await user_b.download.next(timeout=5)
    agents_by_id_b = {a["id"]: a for a in json.loads(response_b.content)["agents"]}
    assert agents_by_id_b["core_metadata"]["provider"] == "opencode"


async def test_saved_agent_edit_does_not_leak_across_hosted_sessions(
    user: User, create_user: Callable[[], User], monkeypatch, tmp_path
) -> None:
    """Hosted mode (VISOR_NATIVE=0) is different real people, not one
    desktop user reopening the app -- session_settings.py's per-browser
    app.storage.user backing must keep a saved agent_overrides choice from
    ever reaching anyone else's session, same guarantee already proven for
    API keys below."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("VISOR_NATIVE", "0")

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-save")

    provider_select = list(user.find(marker="agent-provider-core_metadata").elements)[0]
    original_provider = provider_select.value
    assert original_provider != "opencode"
    provider_select.value = "opencode"
    user.find(marker="agents-save").click()
    user.find(marker="agents-download").click()

    response_a = await user.download.next(timeout=5)
    agents_by_id_a = {a["id"]: a for a in json.loads(response_a.content)["agents"]}
    assert agents_by_id_a["core_metadata"]["provider"] == "opencode"

    user_b = create_user()
    await user_b.open("/")
    user_b.find(marker="tab-agents").click()
    await user_b.should_see(marker="agents-save")
    user_b.find(marker="agents-download").click()

    response_b = await user_b.download.next(timeout=5)
    agents_by_id_b = {a["id"]: a for a in json.loads(response_b.content)["agents"]}
    assert agents_by_id_b["core_metadata"]["provider"] == original_provider


async def test_settings_key_does_not_leak_across_hosted_sessions(
    user: User, create_user: Callable[[], User], monkeypatch, tmp_path
) -> None:
    """Regression: in hosted mode (VISOR_NATIVE=0 -- see visor/session_settings.py),
    every session's Settings tab ultimately read from and wrote to the one
    shared settings.json, so changing a provider's key in one browser was
    visible -- and, worse, silently overwritten -- in every other
    connected session. Each hosted session must get its own private
    VisorSettings, backed by NiceGUI's per-browser app.storage.user."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("VISOR_NATIVE", "0")

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-opencode").click()
    await user.should_see(marker="settings-input-OPENCODE_API_KEY")
    user.find(marker="settings-input-OPENCODE_API_KEY").type("session-a-key")
    user.find(marker="settings-save").click()

    # A second, independent browser session against the same running
    # process -- without per-session storage this would see session A's
    # key (or, after a save of its own, permanently clobber it).
    user_b = create_user()
    await user_b.open("/")
    user_b.find(marker="tab-settings").click()
    await user_b.should_see(marker="settings-provider-edit-opencode")
    user_b.find(marker="settings-provider-edit-opencode").click()
    await user_b.should_see(marker="settings-input-OPENCODE_API_KEY")
    key_input_b = list(user_b.find(marker="settings-input-OPENCODE_API_KEY").elements)[0]
    assert key_input_b.value == ""


async def test_stale_extra_body_from_a_saved_model_switch_is_sanitized_on_next_load(
    user: User, create_user: Callable[[], User], monkeypatch, tmp_path
) -> None:
    """Found on Opus review of the extra_body sanitize fix (agents_page.py's
    sanitize_all_agents_extra_body): config/agents.yaml's core_metadata
    agent statically declares extra_body: {thinking: {type: disabled}} for
    its default opencode/deepseek-v4-flash pairing. Saving a model switch
    to a Responses-API model (muse-spark-1.3-contributor, same provider)
    only ever persists provider/model/temperature/reasoning_effort to
    settings.json -- never extra_body. So a fresh connection rebuilds
    pipeline_config from the base YAML (extra_body still the stale
    "thinking" shape), applies the saved model override on top of it, and
    -- without app.py's own sanitize_all_agents_extra_body() call right
    after apply_agent_overrides()/reconcile_provider_extra_body() -- would
    reach ResponsesLLMClient with that stale key on literally the first
    request of the new session, before the Agents tab's own save-time
    sanitize ever gets a chance to run again."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    # Truthy is enough -- restore_testing_provider_if_key_available only
    # checks presence, never calls the provider. Without this, visor's own
    # openrouter default swap would apply first and this agent would never
    # be on opencode (nor carry the "thinking" extra_body) to begin with.
    monkeypatch.setenv("OPENCODE_API_KEY", "test-key-presence-only")

    await user.open("/")
    user.find(marker="tab-agents").click()
    await user.should_see(marker="agents-save")

    provider_select = list(user.find(marker="agent-provider-core_metadata").elements)[0]
    assert provider_select.value == "opencode"

    model_select = list(user.find(marker="agent-model-core_metadata").elements)[0]
    model_select.set_options(
        [*model_select.options, "muse-spark-1.3-contributor"],
        value="muse-spark-1.3-contributor",
    )
    user.find(marker="agents-save").click()
    await user.should_see("Agent settings updated")

    # A fresh connection -- rebuilds pipeline_config from config/agents.yaml
    # (extra_body still statically "thinking") plus the just-saved
    # provider/model override, same as an app relaunch or a page reload.
    user_b = create_user()
    await user_b.open("/")
    user_b.find(marker="tab-agents").click()
    await user_b.should_see(marker="agents-save")
    user_b.find(marker="agents-download").click()

    response_b = await user_b.download.next(timeout=5)
    agents_by_id_b = {a["id"]: a for a in json.loads(response_b.content)["agents"]}
    core_metadata_b = agents_by_id_b["core_metadata"]
    assert core_metadata_b["model"] == "muse-spark-1.3-contributor"
    assert core_metadata_b["extra_body"] is None
