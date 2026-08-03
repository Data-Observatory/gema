"""Tests for LLMClient Protocol and LLMConfig."""

import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from metadata_enricher.llm.base import LLMClient, LLMConfig


class SomeModel(BaseModel):
    """A simple model used as response_model in tests."""

    name: str = "test"


class MockLLMClient:
    """Mock implementation of LLMClient for testing Protocol conformance."""

    def __init__(self, model_name: str = "mock-model") -> None:
        self._model = model_name

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> BaseModel:
        return response_model()

    def complete_raw(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        return f"Mock response to: {prompt}"


class TestLLMClient:
    """LLMClient Protocol tests."""

    def test_isinstance_check(self) -> None:
        """MockLLMClient satisfies runtime_checkable Protocol."""
        client = MockLLMClient()
        assert isinstance(client, LLMClient)

    def test_complete_returns_model_instance(self) -> None:
        """complete() returns instance of the passed response_model."""
        client = MockLLMClient()
        result = client.complete(prompt="test", response_model=SomeModel)
        assert isinstance(result, SomeModel)

    def test_complete_raw_returns_string(self) -> None:
        """complete_raw() returns a string."""
        client = MockLLMClient()
        result = client.complete_raw(prompt="hello")
        assert isinstance(result, str)
        assert "hello" in result

    def test_model_property(self) -> None:
        """model property returns the configured model name."""
        client = MockLLMClient(model_name="gpt-4")
        assert client.model == "gpt-4"


class TestLLMConfig:
    """LLMConfig Pydantic model tests."""

    def test_minimal_config(self) -> None:
        """Create with required fields only."""
        config = LLMConfig(model="gpt-4", api_key="sk-test")
        assert config.model == "gpt-4"
        assert config.api_key.get_secret_value() == "sk-test"
        assert config.base_url is None
        assert config.temperature == 0.0
        assert config.max_tokens is None
        assert config.timeout == 60.0

    def test_all_fields(self) -> None:
        """Create with all fields explicitly set."""
        config = LLMConfig(
            model="gpt-4",
            api_key="sk-test",
            base_url="https://api.openai.com",
            temperature=0.5,
            max_tokens=1000,
            timeout=30.0,
        )
        assert config.model == "gpt-4"
        assert config.base_url == "https://api.openai.com"
        assert config.temperature == 0.5
        assert config.max_tokens == 1000
        assert config.timeout == 30.0

    def test_rejects_unknown_fields(self) -> None:
        """extra='forbid' raises ValidationError for unknown fields."""
        with pytest.raises(ValidationError):
            LLMConfig(model="gpt-4", api_key="sk-test", unknown="field")

    def test_temperature_default(self) -> None:
        """temperature defaults to 0.0."""
        config = LLMConfig(model="gpt-4", api_key="sk-test")
        assert config.temperature == 0.0

    def test_timeout_default(self) -> None:
        """timeout defaults to 60.0."""
        config = LLMConfig(model="gpt-4", api_key="sk-test")
        assert config.timeout == 60.0

    def test_api_key_stored_as_secret(self) -> None:
        """api_key accepted as plain string, stored as SecretStr internally."""
        config = LLMConfig(model="gpt-4", api_key="sk-xyz")
        assert isinstance(config.api_key, SecretStr)
        assert config.api_key.get_secret_value() == "sk-xyz"
