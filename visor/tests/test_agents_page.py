"""Tests for visor.pages.agents_page's upload handler.

Full click-through (rendering, per-agent cards, Advanced section content)
is covered in test_ui_navigation.py — this file is a focused unit test on
_handle_upload's PipelineConfig field round-trip, the same style already
used for visor.settings/visor.bootstrap (no app boot needed).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from metadata_enricher.config.models import PipelineConfig
from visor.pages.agents_page import _handle_upload, _warn_model_override_mismatches

pytestmark = pytest.mark.asyncio


def _minimal_config_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_name": "datacite-4.6",
        "agents": [
            {
                "id": "a0",
                "name": "Agent 0",
                "fields": ["titles"],
                "prompt": "Do something.",
                "provider": "p0",
            }
        ],
        "providers": [{"name": "p0", "api_key_env": "P0_API_KEY"}],
    }
    base.update(overrides)
    return base


class _FakeFile:
    def __init__(self, text: str) -> None:
        self._text = text

    async def text(self) -> str:
        return self._text


class _FakeUploadEvent:
    def __init__(self, text: str) -> None:
        self.file = _FakeFile(text)


class TestHandleUpload:
    @pytest.fixture(autouse=True)
    def _stub_notify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # _handle_upload calls ui.notify() on both the success and failure
        # paths -- this module boots no NiceGUI client/slot context, which
        # ui.notify() requires. Stub it out; these tests assert on
        # pipeline_config's own state, never on what was displayed.
        monkeypatch.setattr("visor.pages.agents_page.ui.notify", lambda *a, **k: None)

    async def test_carries_enable_content_fetch_and_doi_resolution(self) -> None:
        """Regression: _handle_upload copies every other top-level
        PipelineConfig scalar (enable_identifier_enrichment, validate_pids,
        ...) from the uploaded/validated config back onto the live one, but
        used to miss these two -- an uploaded file with either flag set
        would silently revert to the default (False) the moment it was
        applied."""
        pipeline_config = PipelineConfig(**_minimal_config_dict())
        assert pipeline_config.enable_content_fetch is False
        assert pipeline_config.enable_doi_resolution is False

        uploaded = _minimal_config_dict(enable_content_fetch=True, enable_doi_resolution=True)
        event = _FakeUploadEvent(json.dumps(uploaded))
        refreshed: list[bool] = []

        await _handle_upload(event, pipeline_config, lambda: refreshed.append(True))

        assert pipeline_config.enable_content_fetch is True
        assert pipeline_config.enable_doi_resolution is True
        assert refreshed == [True]

    async def test_carries_validate_shacl_conformance(self) -> None:
        """Same class of regression as above, found on review: _download()
        serializes the whole model (model_dump), so a downloaded config
        always carries validate_shacl_conformance -- but _handle_upload's
        manual field-by-field copy stopped at validate_pids_live and never
        picked this one up, silently reverting it to the default (False)
        on every download/edit/upload round-trip."""
        pipeline_config = PipelineConfig(**_minimal_config_dict())
        assert pipeline_config.validate_shacl_conformance is False

        uploaded = _minimal_config_dict(validate_shacl_conformance=True)
        event = _FakeUploadEvent(json.dumps(uploaded))
        refreshed: list[bool] = []

        await _handle_upload(event, pipeline_config, lambda: refreshed.append(True))

        assert pipeline_config.validate_shacl_conformance is True
        assert refreshed == [True]

    async def test_rejects_invalid_upload_without_mutating_config(self) -> None:
        pipeline_config = PipelineConfig(**_minimal_config_dict())
        event = _FakeUploadEvent("not json")
        refreshed: list[bool] = []

        await _handle_upload(event, pipeline_config, lambda: refreshed.append(True))

        assert pipeline_config.enable_content_fetch is False
        assert refreshed == []


class TestWarnModelOverrideMismatches:
    """_warn_model_override_mismatches -- the save-time UI surface for
    find_model_override_elsewhere() (pure-function coverage lives in
    test_config_models.py). Uses a synthetic model/provider pair, not any
    real model -- this is a generic model-call-architecture fix, not
    special-cased to whichever model first surfaced the underlying bug.

    Bodies are all sync work, but declared async like their neighbours
    since this module's pytestmark is asyncio for all of them."""

    @pytest.fixture
    def _notify_calls(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        monkeypatch.setattr(
            "visor.pages.agents_page.ui.notify",
            lambda *a, **k: calls.append(k),
        )
        return calls

    def _config_with_mismatch(self) -> PipelineConfig:
        raw = _minimal_config_dict(
            providers=[
                {"name": "p0", "api_key_env": "P0_API_KEY"},
                {
                    "name": "p1",
                    "api_key_env": "P1_API_KEY",
                    "model_overrides": [{"model": "special-model", "api_style": "responses"}],
                },
            ]
        )
        raw["agents"][0]["model"] = "special-model"  # agent stays on p0, the wrong provider
        return PipelineConfig(**raw)

    async def test_warns_when_model_needs_a_different_providers_override(
        self, _notify_calls: list[dict[str, Any]]
    ) -> None:
        pipeline_config = self._config_with_mismatch()
        _warn_model_override_mismatches(pipeline_config, None)
        assert len(_notify_calls) == 1
        assert _notify_calls[0]["type"] == "warning"

    async def test_no_warning_when_agent_already_on_the_right_provider(
        self, _notify_calls: list[dict[str, Any]]
    ) -> None:
        pipeline_config = self._config_with_mismatch()
        pipeline_config.agents[0].provider = "p1"
        _warn_model_override_mismatches(pipeline_config, None)
        assert _notify_calls == []

    async def test_no_warning_when_agent_has_no_model_set(
        self, _notify_calls: list[dict[str, Any]]
    ) -> None:
        pipeline_config = PipelineConfig(**_minimal_config_dict())
        assert pipeline_config.agents[0].model is None
        _warn_model_override_mismatches(pipeline_config, None)
        assert _notify_calls == []

    async def test_dedupes_identical_mismatches_across_agents(
        self, _notify_calls: list[dict[str, Any]]
    ) -> None:
        """A bulk provider switch can put every agent onto the same wrong
        provider in one click -- one toast for that, not one per agent."""
        raw = _minimal_config_dict(
            agents=[
                {
                    "id": "a0",
                    "name": "Agent 0",
                    "fields": ["titles"],
                    "prompt": "Do something.",
                    "provider": "p0",
                    "model": "special-model",
                },
                {
                    "id": "a1",
                    "name": "Agent 1",
                    "fields": ["titles"],
                    "prompt": "Do something else.",
                    "provider": "p0",
                    "model": "special-model",
                },
            ],
            providers=[
                {"name": "p0", "api_key_env": "P0_API_KEY"},
                {
                    "name": "p1",
                    "api_key_env": "P1_API_KEY",
                    "model_overrides": [{"model": "special-model", "api_style": "responses"}],
                },
            ],
        )
        pipeline_config = PipelineConfig(**raw)

        _warn_model_override_mismatches(pipeline_config, None)

        assert len(_notify_calls) == 1


class TestAdvancedSection:
    """The read-only "Advanced" expansion. Rendered here against a
    hand-built PipelineConfig rather than in test_ui_navigation.py's
    click-through: the real config/agents.yaml sets no agent-level
    reasoning_effort, and the app-boot harness (runpy of visor/app.py at
    fixture-setup time) leaves no seam to inject one from a test body."""

    async def test_shows_reasoning_effort_when_an_agent_sets_it(self) -> None:
        """AgentConfig.reasoning_effort is a real, settable per-agent field
        (config/agents.yaml uses it on a provider model override today) that
        had zero visibility in visor -- not even read-only, unlike its
        neighbours tools/extra_body."""
        from nicegui import ui
        from nicegui.testing import user_simulation

        from visor.pages.agents_page import render_agents

        raw = _minimal_config_dict()
        raw["agents"][0]["reasoning_effort"] = "high"
        pipeline_config = PipelineConfig(**raw)

        def _root() -> None:
            render_agents(ui.column(), pipeline_config)

        async with user_simulation(root=_root) as user:
            await user.open("/")
            await user.should_see("Reasoning effort: high")

    async def test_omits_reasoning_effort_when_unset(self) -> None:
        """Same conditional treatment as tools/extra_body -- an agent that
        never sets it must not grow an empty line."""
        from nicegui import ui
        from nicegui.testing import user_simulation

        from visor.pages.agents_page import render_agents

        pipeline_config = PipelineConfig(**_minimal_config_dict())
        assert pipeline_config.agents[0].reasoning_effort is None

        def _root() -> None:
            render_agents(ui.column(), pipeline_config)

        async with user_simulation(root=_root) as user:
            await user.open("/")
            await user.should_see("Agent 0")
            await user.should_not_see("Reasoning effort")
