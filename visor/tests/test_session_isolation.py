"""Multi-connection hosted-mode regression.

visor is normally a single-user pywebview window, but it can also be hosted
(``VISOR_NATIVE=0``) so several people connect to the *same running
process* over the network. ``main_page()`` used to alias the module-level
``PipelineConfig`` / ``DataverseExportConfig`` instead of copying them, so
one session's Agents-tab edit (provider/model/temperature, mutated in
place — see agents_page.py's module docstring) leaked into every other
session. Each session is meant to be able to manage its own config
independently, without affecting anyone else's.

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


async def test_agent_edit_does_not_leak_across_sessions(
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
    user.find(marker="agents-save").click()
    user.find(marker="agents-download").click()

    response_a = await user.download.next(timeout=5)
    agents_by_id_a = {a["id"]: a for a in json.loads(response_a.content)["agents"]}
    assert agents_by_id_a["core_metadata"]["provider"] == "opencode"

    # A fresh session on the same running app -- without the deep-copy fix
    # this sees session A's mutated shared PipelineConfig object instead of
    # a clean copy of the one loaded at module import time.
    user_b = create_user()
    await user_b.open("/")
    user_b.find(marker="tab-agents").click()
    await user_b.should_see(marker="agents-save")
    user_b.find(marker="agents-download").click()

    response_b = await user_b.download.next(timeout=5)
    agents_by_id_b = {a["id"]: a for a in json.loads(response_b.content)["agents"]}
    assert agents_by_id_b["core_metadata"]["provider"] == original_provider
