"""Real click-through test of the full visor app.

Uses NiceGUI's in-process user-simulation harness (nicegui.testing.User) —
no browser, but real app code, real click handlers, real async scheduling
against the actual FastAPI/Uvicorn app object graph visor/app.py builds.

Marked @pytest.mark.live: the Run step makes a real LLM call. Deliberately
NOT gated by "skip if no key is set" alone — that check is not reliable
across every environment this might run in (observed directly: a run
here proceeded with a real key even when a separate same-shell check
moments earlier showed none in os.environ). The actual safety net is
`make test-visor` always passing `-m "not live"`; this file only runs via
the explicit `make test-visor-live` target. Needs pytest-asyncio, already
present transitively via the deepeval dev dependency — this file is the
one place in visor/tests that needs it, because NiceGUI's testing
framework is inherently async; tests/ (the library suite) stays sync-only
per project convention regardless.
"""

from __future__ import annotations

import json
import os

import pytest
from nicegui.testing import User

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.live,
    pytest.mark.nicegui_main_file("visor/app.py"),
]


async def test_full_click_through_settings_to_download(user: User, monkeypatch, tmp_path) -> None:
    """Settings (fresh, no saved key) -> fill required key -> Save ->
    Run form -> fill url/title/description -> Run (real LLM call) ->
    Result -> Download, asserting the exact bytes handed to ui.download."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    await user.open("/")
    await user.should_see(marker="settings-save")

    real_key = os.environ.get("ZAI_API_KEY")
    if not real_key:
        pytest.skip("this pipeline config's default provider needs ZAI_API_KEY specifically")
    user.find(marker="settings-input-ZAI_API_KEY").type(real_key)
    user.find(marker="settings-save").click()

    await user.should_see(marker="run-submit")

    user.find(marker="run-input-url").type("https://datos.gob.cl/dataset/visor-e2e-smoke-test")
    user.find(marker="run-input-title").type("Visor End-to-End Smoke Test Dataset")
    user.find(marker="run-input-description").type(
        "A minimal synthetic dataset description used only to verify visor's "
        "click-through flow end to end, from a real LLM call through to a "
        "downloadable JSON result."
    )
    user.find(marker="run-submit").click()

    # Real multi-agent LLM pipeline run — genuinely slow, not a UI delay.
    await user.should_see(marker="result-success", retries=1800)

    user.find(marker="result-download").click()
    response = await user.download.next(timeout=15)
    assert response.status_code == 200

    payload = json.loads(response.content)
    assert "titles" in payload
    assert isinstance(payload["titles"], list) and payload["titles"]
