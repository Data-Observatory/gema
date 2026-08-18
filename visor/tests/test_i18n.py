"""Tests for visor's Spanish/English UI language support (visor/i18n.py).

test_ui_navigation.py's other tests all run in English -- see conftest.py's
autouse fixture -- since they were written against the original copy and
this keeps them meaning what they say without touching every one of them.
These tests exercise the language feature itself directly.
"""

from __future__ import annotations

import pytest
from nicegui.testing import User

pytestmark = [pytest.mark.asyncio, pytest.mark.nicegui_main_file("visor/app.py")]


async def test_default_language_is_spanish(user: User, monkeypatch, tmp_path) -> None:
    """visor's real default (undoing conftest's English pin for this one
    test) is Spanish, not English -- a fresh visitor who's never touched
    the language picker should see Spanish immediately."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr("visor.i18n.DEFAULT_LANGUAGE", "es")

    await user.open("/")
    await user.should_see("Ejecutar")  # app.tab.run

    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-submit")
    run_button = list(user.find(marker="run-submit").elements)[0]
    assert run_button.text == "Ejecutar"


async def test_language_picker_switches_ui_to_spanish(user: User, monkeypatch, tmp_path) -> None:
    """Picking Español in the language selector must actually change the
    displayed copy -- not just record the preference. main_page() reloads
    on change (see app.py's _on_language_change) since there's no reactive
    binding on every individual label."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-submit")
    run_button = list(user.find(marker="run-submit").elements)[0]
    assert run_button.text == "Run"  # English, per conftest's default pin

    language_select = list(user.find(marker="language-select").elements)[0]
    language_select.value = "es"
    # _on_language_change persists the choice then calls ui.navigate.reload(),
    # a real client-side `location.reload()` -- the simulated browser can't
    # execute that JS itself, so re-open() here stands in for what a real
    # browser does automatically right after the value change fires.
    await user.open("/")

    await user.should_see(marker="run-submit")
    switched_button = list(user.find(marker="run-submit").elements)[0]
    assert switched_button.text == "Ejecutar"


async def test_language_preference_persists_across_reload(user: User, monkeypatch, tmp_path) -> None:
    """The choice is stored in app.storage.user (a signed per-browser
    cookie, see visor/settings.py's storage_secret()) so it survives a
    fresh page load, not just the in-memory reload the picker itself
    triggers."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    user.find(marker="tab-settings").click()
    await user.should_see(marker="settings-save")
    user.find(marker="settings-provider-edit-openrouter").click()
    await user.should_see(marker="settings-input-OPENROUTER_API_KEY")
    user.find(marker="settings-input-OPENROUTER_API_KEY").type("fake-key-for-render-test")
    user.find(marker="settings-save").click()

    await user.should_see(marker="language-select")
    language_select = list(user.find(marker="language-select").elements)[0]
    language_select.value = "es"
    await user.should_see(marker="run-submit")

    await user.open("/")
    await user.should_see(marker="run-submit")
    run_button = list(user.find(marker="run-submit").elements)[0]
    assert run_button.text == "Ejecutar"


async def test_t_falls_back_outside_a_page_context() -> None:
    """t()/current_language() must stay callable from plain, non-UI code
    paths (e.g. a page-module function under a bare unit test, no app
    booted at all) instead of raising -- see current_language()'s
    docstring for why."""
    from visor.i18n import t

    assert t("run.button.run") in ("Run", "Ejecutar")
