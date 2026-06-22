"""Tests for InstructorLLMClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic import BaseModel

from metadata_enricher.llm.base import LLMConfig
from metadata_enricher.llm.instructor_client import InstructorLLMClient


class SimpleOutput(BaseModel):
    """Simple response model for testing."""

    name: str


class TestInstructorLLMClient:
    """InstructorLLMClient tests."""

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_constructor_without_base_url(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """Constructor does not pass base_url when it is None."""
        config = LLMConfig(model="gpt-4", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        mock_openai.assert_called_once_with(
            api_key="sk-test",
            timeout=60.0,
        )
        mock_instructor.from_openai.assert_called_once_with(mock_openai.return_value)
        assert client._config is config
        assert client._max_retries == 3

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_constructor_with_base_url(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """Constructor passes base_url when provided."""
        config = LLMConfig(
            model="gpt-4",
            api_key="sk-test",
            base_url="https://custom.api.com",
        )
        client = InstructorLLMClient(config=config)

        mock_openai.assert_called_once_with(
            api_key="sk-test",
            timeout=60.0,
            base_url="https://custom.api.com",
        )
        mock_instructor.from_openai.assert_called_once_with(mock_openai.return_value)
        assert client._max_retries == 3

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_model_property(self, mock_instructor: MagicMock, mock_openai: MagicMock) -> None:
        """model returns the configured model name unchanged."""
        config = LLMConfig(model="custom-model", api_key="sk-test")
        client = InstructorLLMClient(config=config)
        assert client.model == "custom-model"

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_passes_model_as_is(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete() passes model name without any prefix."""
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        fake_response = SimpleOutput(name="test")
        client._instructor_client.chat.completions.create.return_value = fake_response

        result = client.complete(prompt="hello", response_model=SimpleOutput)

        call_kwargs = client._instructor_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "my-model"
        assert "openai/" not in call_kwargs["model"]
        assert result is fake_response

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_includes_system_message(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete() includes system message when system_prompt is given."""
        config = LLMConfig(model="gpt-4", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        client.complete(
            prompt="user prompt",
            response_model=SimpleOutput,
            system_prompt="system prompt",
        )

        call_kwargs = client._instructor_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "system prompt"}
        assert messages[1] == {"role": "user", "content": "user prompt"}

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_omits_system_message(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete() omits system message when system_prompt is None."""
        config = LLMConfig(model="gpt-4", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        client.complete(prompt="user prompt", response_model=SimpleOutput)

        call_kwargs = client._instructor_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "user prompt"}

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_raw_returns_content(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete_raw() returns the message content."""
        config = LLMConfig(model="gpt-4", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        mock_message = MagicMock()
        mock_message.content = "raw response"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        client._raw_client.chat.completions.create.return_value = mock_response

        result = client.complete_raw(prompt="hello")

        assert result == "raw response"
        call_kwargs = client._raw_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4"
        assert call_kwargs["messages"] == [{"role": "user", "content": "hello"}]

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_raw_handles_none_content(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete_raw() returns empty string when content is None."""
        config = LLMConfig(model="gpt-4", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        mock_message = MagicMock()
        mock_message.content = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        client._raw_client.chat.completions.create.return_value = mock_response

        result = client.complete_raw(prompt="hello")
        assert result == ""
