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

from metadata_enricher.config.models import PipelineConfig, ProviderConfig
from visor.pages.agents_page import (
    _handle_upload,
    sanitize_all_agents_extra_body,
    _sanitize_extra_body_for_responses_api,
    _warn_model_override_mismatches,
)

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
            await user.should_not_see("Reasoning effort:")

    async def test_shows_resolved_reasoning_effort_from_a_provider_model_override(self) -> None:
        """The common real shape (config/agents.yaml's own opencode/
        muse-spark-1.3-contributor pairing): reasoning_effort lives on the
        provider's model_overrides entry, not the agent itself -- found
        missing on review 2026-09-08: an agent with no per-agent
        reasoning_effort set showed nothing here even when its provider
        resolved one via model_overrides, the same cascade
        create_llm_client actually uses."""
        from nicegui import ui
        from nicegui.testing import user_simulation

        from visor.pages.agents_page import render_agents

        raw = _minimal_config_dict(
            providers=[
                {
                    "name": "p0",
                    "api_key_env": "P0_API_KEY",
                    "model_overrides": [
                        {"model": "special-model", "api_style": "responses", "reasoning_effort": "high"}
                    ],
                }
            ]
        )
        raw["agents"][0]["model"] = "special-model"
        pipeline_config = PipelineConfig(**raw)
        assert pipeline_config.agents[0].reasoning_effort is None

        def _root() -> None:
            render_agents(ui.column(), pipeline_config)

        async with user_simulation(root=_root) as user:
            await user.open("/")
            await user.should_see("Reasoning effort: high")

    async def test_omits_resolved_reasoning_effort_on_chat_completions_models(self) -> None:
        """A provider's model_overrides entry for some *other* model must
        not leak a reasoning_effort display onto an agent using a plain
        chat_completions model -- effective_api_style is per-model, and
        this display must respect that the same way create_llm_client
        does."""
        from nicegui import ui
        from nicegui.testing import user_simulation

        from visor.pages.agents_page import render_agents

        raw = _minimal_config_dict(
            providers=[
                {
                    "name": "p0",
                    "api_key_env": "P0_API_KEY",
                    "model_overrides": [
                        {"model": "special-model", "api_style": "responses", "reasoning_effort": "high"}
                    ],
                }
            ]
        )
        raw["agents"][0]["model"] = "plain-chat-model"
        pipeline_config = PipelineConfig(**raw)

        def _root() -> None:
            render_agents(ui.column(), pipeline_config)

        async with user_simulation(root=_root) as user:
            await user.open("/")
            await user.should_see("Agent 0")
            await user.should_not_see("Reasoning effort:")


class TestSanitizeExtraBodyForResponsesApi:
    """Found 2026-09-08: switching an agent's model onto a Responses-API
    model (e.g. opencode/muse-spark-1.3-contributor) while a Chat-Completions
    -shaped extra_body (e.g. ``{"thinking": {"type": "disabled"}}``, left
    over from deepseek-v4-flash) is still sitting on it doesn't clear that
    key -- ResponsesLLMClient drops it and logs a warning on every single
    call, forever, since nothing in visor ever re-checks extra_body once a
    model changes."""

    async def test_strips_unsupported_keys_when_resolved_api_style_is_responses(self) -> None:
        provider = ProviderConfig(
            name="p0",
            api_key_env="P0_API_KEY",
            model_overrides=[{"model": "muse", "api_style": "responses"}],
        )

        result = _sanitize_extra_body_for_responses_api(
            {"thinking": {"type": "disabled"}, "keep": "me"}, provider, "muse"
        )

        assert result == {"keep": "me"}

    async def test_returns_none_rather_than_an_empty_dict_when_nothing_survives(self) -> None:
        provider = ProviderConfig(
            name="p0",
            api_key_env="P0_API_KEY",
            model_overrides=[{"model": "muse", "api_style": "responses"}],
        )

        result = _sanitize_extra_body_for_responses_api(
            {"thinking": {"type": "disabled"}, "seed": 42}, provider, "muse"
        )

        assert result is None

    async def test_leaves_chat_completions_models_untouched(self) -> None:
        provider = ProviderConfig(name="p0", api_key_env="P0_API_KEY")

        result = _sanitize_extra_body_for_responses_api(
            {"thinking": {"type": "disabled"}}, provider, "plain-chat-model"
        )

        assert result == {"thinking": {"type": "disabled"}}

    async def test_noop_when_extra_body_provider_or_model_missing(self) -> None:
        assert _sanitize_extra_body_for_responses_api(None, None, None) is None
        assert _sanitize_extra_body_for_responses_api({}, None, "m") == {}
        provider = ProviderConfig(name="p0", api_key_env="P0_API_KEY")
        assert _sanitize_extra_body_for_responses_api({"seed": 1}, provider, None) == {"seed": 1}

    async def test_strips_when_api_style_is_responses_at_the_provider_level(self) -> None:
        """Same outcome as the model_overrides-scoped test above, but via
        the OTHER branch of effective_api_style's cascade -- a provider
        that sets api_style: responses directly, with no per-model
        override at all. Only the model_overrides path had coverage."""
        provider = ProviderConfig(name="p0", api_key_env="P0_API_KEY", api_style="responses")

        result = _sanitize_extra_body_for_responses_api(
            {"thinking": {"type": "disabled"}, "keep": "me"}, provider, "any-model"
        )

        assert result == {"keep": "me"}


class TestSanitizeAllAgentsExtraBody:
    async def test_sanitizes_every_agent_using_its_own_resolved_provider(self) -> None:
        raw = _minimal_config_dict(
            providers=[
                {
                    "name": "p0",
                    "api_key_env": "P0_API_KEY",
                    "model_overrides": [{"model": "muse", "api_style": "responses"}],
                }
            ],
        )
        raw["agents"][0]["model"] = "muse"
        raw["agents"][0]["extra_body"] = {"thinking": {"type": "disabled"}}
        pipeline_config = PipelineConfig(**raw)

        sanitize_all_agents_extra_body(pipeline_config, None)

        assert pipeline_config.agents[0].extra_body is None

    async def test_leaves_a_chat_completions_agents_extra_body_alone(self) -> None:
        raw = _minimal_config_dict()
        raw["agents"][0]["extra_body"] = {"thinking": {"type": "disabled"}}
        pipeline_config = PipelineConfig(**raw)

        sanitize_all_agents_extra_body(pipeline_config, None)

        assert pipeline_config.agents[0].extra_body == {"thinking": {"type": "disabled"}}

    async def test_sanitizes_the_dataverse_agent_too(self) -> None:
        """Found on Opus review: every existing test only checked
        pipeline_config.agents -- deleting the dataverse_export_config
        branch inside sanitize_all_agents_extra_body entirely broke
        nothing until now."""
        from metadata_enricher.config.models import AgentConfig, DataverseExportConfig

        raw = _minimal_config_dict(
            providers=[
                {
                    "name": "p0",
                    "api_key_env": "P0_API_KEY",
                    "model_overrides": [{"model": "muse", "api_style": "responses"}],
                }
            ],
        )
        pipeline_config = PipelineConfig(**raw)
        dataverse_export_config = DataverseExportConfig(
            agent=AgentConfig(
                id="dataverse",
                name="Dataverse",
                fields=["schema_keywords"],
                prompt="Classify.",
                provider="p0",
                model="muse",
                extra_body={"thinking": {"type": "disabled"}},
            )
        )

        sanitize_all_agents_extra_body(pipeline_config, dataverse_export_config)

        assert dataverse_export_config.agent.extra_body is None
