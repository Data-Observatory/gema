"""Tests for visor.session_settings — no NiceGUI page needed for the native
mode branch or build_llm_factory (both are plain functions); the hosted
app.storage.user branch is exercised at the click-through level in
test_session_isolation.py instead, since app.storage.user requires a real
request/page context to access at all.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from metadata_enricher.config.models import ProviderConfig
from visor.session_settings import build_llm_factory, load_session_settings, save_session_settings
from visor.settings import VisorSettings


class TestNativeModeDelegatesToFile:
    def test_load_reads_the_plain_file(self, monkeypatch, tmp_path) -> None:
        monkeypatch.delenv("VISOR_NATIVE", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        save_session_settings(VisorSettings(env={"K": "v"}))
        assert load_session_settings() == VisorSettings(env={"K": "v"})

    def test_explicit_native_one_also_uses_the_file(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("VISOR_NATIVE", "1")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        save_session_settings(VisorSettings(env={"K": "v"}))
        assert load_session_settings() == VisorSettings(env={"K": "v"})


class TestBuildLlmFactory:
    """The actual fix for the LLM-key hosted-session race: the returned
    factory must pass THIS session's own key explicitly, never rely on
    os.environ (which is process-wide and can't hold two sessions' keys
    for the same provider at once)."""

    def test_passes_this_sessions_key_explicitly(self, monkeypatch) -> None:
        mock_create = MagicMock(return_value="fake-client")
        monkeypatch.setattr("visor.session_settings.create_llm_client", mock_create)

        provider = ProviderConfig(name="p", api_key_env="P_API_KEY")
        factory = build_llm_factory(VisorSettings(env={"P_API_KEY": "session-key"}))
        result = factory(provider, model="gpt-4", temperature=0.5)

        assert result == "fake-client"
        mock_create.assert_called_once_with(
            provider,
            model="gpt-4",
            temperature=0.5,
            max_tokens=None,
            extra_body=None,
            api_key="session-key",
        )

    def test_falls_back_to_none_when_this_session_has_no_key_for_the_provider(
        self, monkeypatch
    ) -> None:
        """None (not "" or KeyError) so create_llm_client falls through to
        its normal os.environ lookup for a provider this session simply
        doesn't have a key for -- not an error case."""
        mock_create = MagicMock(return_value="fake-client")
        monkeypatch.setattr("visor.session_settings.create_llm_client", mock_create)

        provider = ProviderConfig(name="p", api_key_env="OTHER_API_KEY")
        factory = build_llm_factory(VisorSettings(env={}))
        factory(provider, model="gpt-4")

        assert mock_create.call_args.kwargs["api_key"] is None

    def test_two_sessions_get_independent_factories(self, monkeypatch) -> None:
        """The regression this whole module exists to fix: two concurrent
        sessions' factories, built from their own settings, must never
        resolve to the same key for the same provider."""
        mock_create = MagicMock(side_effect=lambda *a, **kw: kw["api_key"])
        monkeypatch.setattr("visor.session_settings.create_llm_client", mock_create)

        provider = ProviderConfig(name="p", api_key_env="P_API_KEY")
        factory_a = build_llm_factory(VisorSettings(env={"P_API_KEY": "key-a"}))
        factory_b = build_llm_factory(VisorSettings(env={"P_API_KEY": "key-b"}))

        assert factory_a(provider, model="gpt-4") == "key-a"
        assert factory_b(provider, model="gpt-4") == "key-b"
