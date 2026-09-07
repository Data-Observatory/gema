"""Tests for the LLM client factory (metadata_enricher.llm.factory).

Uses ``unittest.mock`` to avoid real network calls.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from metadata_enricher.cache import CachedLLMClient, CacheManager
from metadata_enricher.config.loader import load_config
from metadata_enricher.config.models import ProviderConfig
from metadata_enricher.llm.base import LLMClient
from metadata_enricher.llm.factory import _client_cache, create_llm_client, reset_client_cache
from metadata_enricher.llm.instructor_client import InstructorLLMClient
from metadata_enricher.llm.responses_client import ResponsesLLMClient
from metadata_enricher.llm.retry import RetryableLLMClient


@pytest.fixture(autouse=True)
def reset_cache():
    reset_client_cache()
    yield
    reset_client_cache()


@pytest.fixture
def mock_instructor():
    with patch("metadata_enricher.llm.factory.InstructorLLMClient") as mock:
        mock_instance = MagicMock()
        # Make the mock instance satisfy LLMClient protocol structurally
        mock_instance.model = "test-model"
        mock_instance._config = SimpleNamespace(temperature=0.0, seed=None)
        del mock_instance.inner
        mock.return_value = mock_instance
        yield mock


def make_provider(
    name: str = "test-provider",
    base_url: str | None = "http://localhost:8080",
    api_key_env: str = "TEST_API_KEY",
    session_header: str | None = None,
) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
        session_header=session_header,
    )


class TestFactory:
    """Tests for create_llm_client."""

    def test_factory_creates_client(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """Returns a client that satisfies the LLMClient protocol."""
        monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
        client = create_llm_client(
            provider=make_provider(),
            model="gpt-4",
        )
        assert hasattr(client, "complete")
        assert hasattr(client, "complete_raw")
        # Conforms to the LLMClient protocol
        assert isinstance(client, LLMClient)

    def test_factory_passes_provider_session_header_to_llm_config(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """provider.session_header reaches InstructorLLMClient's LLMConfig."""
        monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
        create_llm_client(
            provider=make_provider(session_header="x-opencode-session"),
            model="gpt-4",
        )
        called_config = mock_instructor.call_args.kwargs["config"]
        assert called_config.session_header == "x-opencode-session"

    def test_factory_raises_on_missing_key(self) -> None:
        """Raises ValueError when the API key env var is not set."""
        with pytest.raises(ValueError, match="TEST_API_KEY"):
            create_llm_client(
                provider=make_provider(),
                model="gpt-4",
            )

    def test_same_provider_returns_cached_client(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """Same provider name returns the same client instance."""
        monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
        provider = make_provider()

        client_a = create_llm_client(provider, model="gpt-4")
        client_b = create_llm_client(provider, model="gpt-4")

        assert client_a is client_b

    def test_different_providers_different_clients(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """Different provider names return different client instances."""
        monkeypatch.setenv("KEY_A", "sk-a")
        monkeypatch.setenv("KEY_B", "sk-b")

        provider_a = make_provider(name="provider-a", api_key_env="KEY_A")
        provider_b = make_provider(name="provider-b", api_key_env="KEY_B")

        client_a = create_llm_client(provider_a, model="gpt-4")
        client_b = create_llm_client(provider_b, model="gpt-4")

        assert client_a is not client_b

    def test_factory_with_cache_disabled(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """With use_cache=False, the client has no CachedLLMClient wrapper."""
        monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
        client = create_llm_client(
            provider=make_provider(),
            model="gpt-4",
            use_cache=False,
        )
        assert not isinstance(client, CachedLLMClient)
        # With retry still enabled, it should be a RetryableLLMClient
        assert isinstance(client, RetryableLLMClient)

    def test_factory_with_retry_disabled(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """With use_retry=False, the client has no RetryableLLMClient wrapper."""
        monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
        client = create_llm_client(
            provider=make_provider(),
            model="gpt-4",
            use_retry=False,
        )
        assert not isinstance(client, RetryableLLMClient)
        # With cache still enabled, it should be a CachedLLMClient
        assert isinstance(client, CachedLLMClient)

    def test_reset_clears_cache(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """After reset, creating the same provider yields a new instance."""
        monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
        provider = make_provider()

        client_a = create_llm_client(provider, model="gpt-4")
        reset_client_cache()
        client_b = create_llm_client(provider, model="gpt-4")

        assert client_a is not client_b
        assert len(_client_cache) == 1

    def test_different_temperature_different_clients(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """Same provider + model but different temperature yields different clients."""
        monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
        provider = make_provider()

        client_a = create_llm_client(provider, model="gpt-4", temperature=0.7)
        client_b = create_llm_client(provider, model="gpt-4", temperature=0.2)

        assert client_a is not client_b

    def test_different_seed_different_clients(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """Same provider + model + temperature but different seed yields different clients."""
        monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
        provider = make_provider()

        client_a = create_llm_client(provider, model="gpt-4", seed=42)
        client_b = create_llm_client(provider, model="gpt-4", seed=99)

        assert client_a is not client_b


class TestExplicitApiKey:
    """api_key=... bypasses provider.api_key_env/os.environ entirely --
    visor's per-session key injection needs this (see visor/glue.py):
    os.environ is one process-wide value, unusable once two hosted
    sessions hold different keys for the same provider."""

    def test_works_without_the_env_var_set(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        monkeypatch.delenv("TEST_API_KEY", raising=False)
        client = create_llm_client(
            provider=make_provider(), model="gpt-4", api_key="sk-explicit-123"
        )
        assert hasattr(client, "complete")

    def test_takes_precedence_over_the_env_var(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        monkeypatch.setenv("TEST_API_KEY", "sk-from-environ")
        create_llm_client(provider=make_provider(), model="gpt-4", api_key="sk-explicit-123")

        config = mock_instructor.call_args.kwargs["config"]
        assert config.api_key.get_secret_value() == "sk-explicit-123"

    def test_different_explicit_keys_do_not_share_a_cached_client(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """The actual bug this parameter exists to fix: two sessions with
        different keys for the same provider/model must never collide on
        one cached client and silently share whichever key built it
        first."""
        monkeypatch.delenv("TEST_API_KEY", raising=False)
        provider = make_provider()

        client_a = create_llm_client(provider, model="gpt-4", api_key="sk-session-a")
        client_b = create_llm_client(provider, model="gpt-4", api_key="sk-session-b")

        assert client_a is not client_b
        assert len(_client_cache) == 2

    def test_same_explicit_key_returns_the_cached_client(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        monkeypatch.delenv("TEST_API_KEY", raising=False)
        provider = make_provider()

        client_a = create_llm_client(provider, model="gpt-4", api_key="sk-session-a")
        client_b = create_llm_client(provider, model="gpt-4", api_key="sk-session-a")

        assert client_a is client_b

    def test_env_var_path_cache_key_is_unaffected(
        self, monkeypatch: pytest.MonkeyPatch, mock_instructor: MagicMock
    ) -> None:
        """Omitting api_key (every existing call site) must keep producing
        the exact same cache key shape as before -- no `|k=...` suffix."""
        monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
        create_llm_client(provider=make_provider(), model="gpt-4")
        assert list(_client_cache.keys()) == ["test-provider|gpt-4|t=0.0|seed=None|mt=None|c=True|r=True|eb=None"]


class TestResponsesClientProtocolConformance:
    """Guards against the exact silent-degradation trap where
    RetryableLLMClient/CachedLLMClient quietly fall back to plain complete()
    if complete_with_tools is missing on some future third leaf class."""

    def test_responses_client_implements_all_four_protocol_methods(self) -> None:
        from metadata_enricher.llm.base import LLMConfig

        config = LLMConfig(model="my-model", api_key="sk-test", api_style="responses")
        with patch("metadata_enricher.llm.responses_client.OpenAI"):
            client = ResponsesLLMClient(config=config)
        for method_name in (
            "complete",
            "complete_raw",
            "complete_with_usage",
            "complete_with_tools",
        ):
            assert hasattr(client, method_name)
            assert callable(getattr(client, method_name))


class TestRealConfigRegressionGuard:
    """The single most important test in this file: every provider/model
    combo actually wired in the real, committed config/agents.yaml (and the
    autofill preset pool in config/providers.yaml) must resolve to
    api_style="chat_completions" and build an InstructorLLMClient-terminated
    chain today -- nothing is wired to "responses" outside test fixtures.

    The cache-key literals below were computed ONCE against the real
    committed config, from a script mirroring exactly how
    AgentRegistry._build_agents calls create_llm_client -- pinned here as
    literals rather than recomputed, so a future change that silently
    alters either key's shape for the default (chat_completions) path fails
    this test instead of silently invalidating every committed
    golden-fixture cache entry (tests/fixtures/golden/cache/cache.db).
    """

    def test_every_configured_agent_provider_model_resolves_to_chat_completions(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("OPENCODE_API_KEY", "sk-fake-for-regression-guard")
        config = load_config(Path("config/agents.yaml"))
        providers_by_name = {p.name: p for p in config.providers}

        pairs = sorted({(a.provider, a.model) for a in config.agents if a.model is not None})
        assert pairs, "config/agents.yaml has no agents with a model set -- guard is vacuous"

        for provider_name, model in pairs:
            provider = providers_by_name[provider_name]
            assert provider.effective_api_style(model) == "chat_completions"

            client = create_llm_client(
                provider, model=model, cache_dir=tmp_path, use_cache=False
            )
            # use_cache=False here yields RetryableLLMClient(InstructorLLMClient) --
            # .inner unwraps to the real leaf without needing to walk past a
            # CachedLLMClient (which has no .inner property, by design).
            leaf = client.inner if hasattr(client, "inner") else client
            assert isinstance(leaf, InstructorLLMClient)
            assert not isinstance(leaf, ResponsesLLMClient)

    def test_known_provider_presets_all_default_to_chat_completions(self) -> None:
        """config/providers.yaml (the autofill preset pool -- see
        cli.py's list-known-providers) must keep every preset on
        api_style="chat_completions" by default too, same as the real
        runtime config -- nothing here opts a preset into "responses" for
        an arbitrary model name."""
        import yaml

        data = yaml.safe_load(Path("config/providers.yaml").read_text(encoding="utf-8"))
        presets = [ProviderConfig.model_validate(p) for p in data["providers"]]
        assert presets
        for preset in presets:
            assert preset.effective_api_style("any-model-name") == "chat_completions"

    def test_factory_cache_key_is_byte_identical_for_real_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("OPENCODE_API_KEY", "sk-fake-for-regression-guard")
        config = load_config(Path("config/agents.yaml"))
        providers_by_name = {p.name: p for p in config.providers}

        for agent in config.agents:
            provider = providers_by_name[agent.provider]
            kwargs: dict[str, object] = {
                "temperature": agent.temperature,
                "max_tokens": agent.max_tokens,
                # Isolate from ~/.cache/gema without changing use_cache (which
                # IS part of the pinned cache-key literal below via "c=...").
                "cache_dir": tmp_path,
            }
            if agent.extra_body is not None:
                kwargs["extra_body"] = agent.extra_body
            create_llm_client(provider, model=agent.model, **kwargs)

        # Pinned literal -- see class docstring.
        assert list(_client_cache.keys()) == [
            'opencode|deepseek-v4-flash|t=0.0|seed=None|mt=None|c=True|r=True'
            '|eb={"thinking": {"type": "disabled"}}'
        ]

    def test_cache_manager_make_key_is_byte_identical_for_default_api_style(self) -> None:
        cm = CacheManager.__new__(CacheManager)
        # Pinned literal -- see class docstring.
        assert (
            cm._make_key("hello", "deepseek-v4-flash", "Foo", 0.0, None)
            == "f6d72d65cca392e5cb1176b89c0569719181372848eec1ce4386a2acf3b63b6e"
        )
