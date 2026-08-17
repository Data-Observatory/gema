"""Multi-connection hosted-mode regressions.

visor is normally a single-user pywebview window, but it can also be hosted
(``VISOR_NATIVE=0``) so several people connect to the *same running
process* over the network. That case has two failure modes covered here:

1. ``main_page()`` used to alias the module-level ``PipelineConfig`` /
   ``DataverseExportConfig`` instead of copying them, so one session's
   Agents-tab edit (provider/model/temperature, mutated in place — see
   agents_page.py's module docstring) leaked into every other session.
2. There was no way for an operator hosting this for people they don't
   fully trust with config (e.g. workshop attendees over Tailscale) to
   hide Settings/Agents and expose only Run.

Uses the same in-process ``nicegui.testing.User`` harness as
test_ui_navigation.py / test_app_e2e.py. The two-session test additionally
uses the ``create_user`` fixture (undocumented here, but shipped by
nicegui.testing.user_plugin) to open a second, independent session against
the same already-running simulated app -- exactly the "second browser tab"
this bug is about.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from nicegui.testing import User

from visor.settings import VisorSettings, save_settings

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


async def test_hosted_guest_hides_settings_and_agents_tabs(
    user: User, monkeypatch, tmp_path
) -> None:
    """VISOR_HOSTED_GUEST=1 removes Settings/Agents entirely and shows only
    the Run panel's content -- Settings is pre-seeded directly here (not
    via the UI) since the whole point is that a guest session has no path
    to it, same as an operator would configure it before sharing the link."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("VISOR_HOSTED_GUEST", "1")
    save_settings(VisorSettings(env={"OPENROUTER_API_KEY": "fake-key-for-render-test"}))

    await user.open("/")

    await user.should_not_see(marker="tab-settings")
    await user.should_not_see(marker="tab-agents")
    await user.should_not_see(marker="tab-run")

    # Run's own content renders directly, and works, with no tabs bar.
    await user.should_see(marker="run-input-url")
    user.find(marker="run-input-url").type("https://example.org/x")
    await user.should_see(marker="run-submit")


async def test_hosted_guest_settings_gate_does_not_navigate_to_hidden_tab(
    user: User, monkeypatch, tmp_path
) -> None:
    """Without a configured key, the Run tab's usual "Go to Settings" gate
    button must not try to jump to a tab that was never created."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("VISOR_HOSTED_GUEST", "1")

    await user.open("/")
    await user.should_see(marker="run-settings-gate")
    user.find("Go to Settings").click()
    await user.should_see("managed by whoever is hosting")
    await user.should_not_see(marker="tab-settings")


async def test_default_unset_hosted_guest_still_shows_all_three_tabs(
    user: User, monkeypatch, tmp_path
) -> None:
    """Regression guard: leaving VISOR_HOSTED_GUEST unset (native mode's
    default) must keep today's exact behavior -- all three tabs present."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("VISOR_HOSTED_GUEST", raising=False)

    await user.open("/")

    await user.should_see(marker="tab-settings")
    await user.should_see(marker="tab-agents")
    await user.should_see(marker="tab-run")
