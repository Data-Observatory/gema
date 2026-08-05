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

    # .type() appends keystrokes like a real browser would — replacing an
    # existing value (core_metadata ships with a default model already set
    # in config/agents.yaml) needs an explicit clear first, same as a user
    # selecting-all before typing over an existing value.
    user.find(marker="agent-model-core_metadata").clear()
    user.find(marker="agent-model-core_metadata").type("test-model-xyz")
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
