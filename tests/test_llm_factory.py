"""Tests for the LLM client factory (metadata_enricher.llm.factory).

Uses ``unittest.mock`` to avoid real network calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from metadata_enricher.cache import CachedLLMClient
from metadata_enricher.config.models import ProviderConfig
from metadata_enricher.llm.base import LLMClient
from metadata_enricher.llm.factory import _client_cache, create_llm_client, reset_client_cache
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
) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
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
