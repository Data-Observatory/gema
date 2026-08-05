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
