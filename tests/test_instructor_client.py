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
            timeout=240.0,
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
            timeout=240.0,
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
    def test_complete_with_usage_extracts_real_token_counts(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        fake_response = SimpleOutput(name="test")
        fake_completion = MagicMock()
        fake_completion.usage.prompt_tokens = 42
        fake_completion.usage.completion_tokens = 8
        fake_completion.usage.total_tokens = 50
        client._instructor_client.chat.completions.create_with_completion.return_value = (
            fake_response,
            fake_completion,
        )

        result, usage = client.complete_with_usage(prompt="hello", response_model=SimpleOutput)

        assert result is fake_response
        assert usage.prompt_tokens == 42
        assert usage.completion_tokens == 8
        assert usage.total_tokens == 50

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_with_usage_defaults_to_zero_when_provider_omits_usage(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """Not every OpenAI-compatible provider returns a usage block —
        must default to zero, never guess or crash."""
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        fake_response = SimpleOutput(name="test")
        fake_completion = MagicMock()
        fake_completion.usage = None
        client._instructor_client.chat.completions.create_with_completion.return_value = (
            fake_response,
            fake_completion,
        )

        result, usage = client.complete_with_usage(prompt="hello", response_model=SimpleOutput)

        assert result is fake_response
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_with_usage_extracts_resolved_model(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """The configured model can be an alias (e.g. OpenRouter's
        '~deepseek/deepseek-v4-flash-latest') -- completion.model is what
        the provider actually served, which is what a user wants to verify
        the real version behind an auto-updating alias."""
        config = LLMConfig(model="~deepseek/deepseek-v4-flash-latest", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        fake_response = SimpleOutput(name="test")
        fake_completion = MagicMock()
        fake_completion.usage = None
        fake_completion.model = "deepseek/deepseek-v4-flash-2508"
        client._instructor_client.chat.completions.create_with_completion.return_value = (
            fake_response,
            fake_completion,
        )

        _result, usage = client.complete_with_usage(prompt="hello", response_model=SimpleOutput)

        assert usage.model == "deepseek/deepseek-v4-flash-2508"

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


class TestCompleteWithTools:
    """Tests for InstructorLLMClient.complete_with_tools's tool-call loop."""

    @staticmethod
    def _raw_response(tool_calls: list[MagicMock] | None, usage: MagicMock | None = None) -> MagicMock:
        message = MagicMock()
        message.tool_calls = tool_calls
        message.content = "thinking..." if tool_calls else "final answer"
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        response.usage = usage
        return response

    @staticmethod
    def _tool_call(call_id: str, name: str, arguments: str) -> MagicMock:
        tc = MagicMock()
        tc.id = call_id
        tc.function.name = name
        tc.function.arguments = arguments
        return tc

    @patch("metadata_enricher.llm.instructor_client.execute_tool")
    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_no_tool_calls_goes_straight_to_final_call(
        self, mock_instructor: MagicMock, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = InstructorLLMClient(config=config)
        client._raw_client.chat.completions.create.return_value = self._raw_response(None)

        fake_result = SimpleOutput(name="test")
        fake_completion = MagicMock()
        fake_completion.usage = None
        client._instructor_client.chat.completions.create_with_completion.return_value = (
            fake_result,
            fake_completion,
        )

        result, usage = client.complete_with_tools(
            prompt="hello", response_model=SimpleOutput, tools=["lookup_organization"]
        )

        assert result is fake_result
        assert usage.total_tokens == 0
        mock_execute_tool.assert_not_called()
        client._raw_client.chat.completions.create.assert_called_once()
        raw_call_kwargs = client._raw_client.chat.completions.create.call_args.kwargs
        assert raw_call_kwargs["tool_choice"] == "auto"
        final_call_kwargs = (
            client._instructor_client.chat.completions.create_with_completion.call_args.kwargs
        )
        assert final_call_kwargs["messages"] == [{"role": "user", "content": "hello"}]

    @patch("metadata_enricher.llm.instructor_client.execute_tool")
    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_tool_call_executed_and_result_fed_back(
        self, mock_instructor: MagicMock, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = InstructorLLMClient(config=config)
        mock_execute_tool.return_value = '{"found": true, "canonical_name": "Universidad de Chile"}'

        tool_call = self._tool_call("call_1", "lookup_organization", '{"name": "U de Chile"}')
        client._raw_client.chat.completions.create.side_effect = [
            self._raw_response([tool_call]),
            self._raw_response(None),
        ]

        fake_result = SimpleOutput(name="test")
        fake_completion = MagicMock()
        fake_completion.usage = None
        client._instructor_client.chat.completions.create_with_completion.return_value = (
            fake_result,
            fake_completion,
        )

        result, _usage = client.complete_with_tools(
            prompt="hello", response_model=SimpleOutput, tools=["lookup_organization"]
        )

        assert result is fake_result
        mock_execute_tool.assert_called_once_with(
            "lookup_organization", {"name": "U de Chile"}
        )
        assert client._raw_client.chat.completions.create.call_count == 2
        final_messages = (
            client._instructor_client.chat.completions.create_with_completion.call_args.kwargs[
                "messages"
            ]
        )
        # The final call gets a fresh [user] pair plus a plain-text summary of
        # the tool exchange -- NOT the raw assistant/tool_calls + tool-role
        # messages from the loop (see complete_with_tools's docstring for why).
        assert final_messages == [
            {"role": "user", "content": "hello"},
            {
                "role": "user",
                "content": (
                    "During your reasoning you looked up the following via tool "
                    "calls -- use these results if relevant to your final answer:\n"
                    '- lookup_organization({"name": "U de Chile"}) -> '
                    '{"found": true, "canonical_name": "Universidad de Chile"}'
                ),
            },
        ]

    @patch("metadata_enricher.llm.instructor_client.execute_tool")
    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_hits_max_tool_rounds_and_still_returns_final_result(
        self, mock_instructor: MagicMock, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        """A model that never stops calling tools must not loop forever —
        the round cap always proceeds to the final structured-output call."""
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = InstructorLLMClient(config=config)
        mock_execute_tool.return_value = '{"found": false}'

        tool_call = self._tool_call("call_1", "lookup_organization", '{"name": "X"}')
        client._raw_client.chat.completions.create.return_value = self._raw_response([tool_call])

        fake_result = SimpleOutput(name="test")
        fake_completion = MagicMock()
        fake_completion.usage = None
        client._instructor_client.chat.completions.create_with_completion.return_value = (
            fake_result,
            fake_completion,
        )

        result, _usage = client.complete_with_tools(
            prompt="hello", response_model=SimpleOutput, tools=["lookup_organization"], max_tool_rounds=2
        )

        assert result is fake_result
        assert client._raw_client.chat.completions.create.call_count == 2
        client._instructor_client.chat.completions.create_with_completion.assert_called_once()

    @patch("metadata_enricher.llm.instructor_client.execute_tool")
    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_token_usage_summed_across_rounds_and_final_call(
        self, mock_instructor: MagicMock, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = InstructorLLMClient(config=config)
        mock_execute_tool.return_value = '{"found": false}'

        round_usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        tool_call = self._tool_call("call_1", "lookup_organization", '{"name": "X"}')
        client._raw_client.chat.completions.create.side_effect = [
            self._raw_response([tool_call], usage=round_usage),
            self._raw_response(None, usage=round_usage),
        ]

        fake_result = SimpleOutput(name="test")
        fake_completion = MagicMock()
        fake_completion.usage = MagicMock(prompt_tokens=20, completion_tokens=8, total_tokens=28)
        client._instructor_client.chat.completions.create_with_completion.return_value = (
            fake_result,
            fake_completion,
        )

        _result, usage = client.complete_with_tools(
            prompt="hello", response_model=SimpleOutput, tools=["lookup_organization"]
        )

        assert usage.prompt_tokens == 10 + 10 + 20
        assert usage.completion_tokens == 5 + 5 + 8
        assert usage.total_tokens == 15 + 15 + 28

    @patch("metadata_enricher.llm.instructor_client.execute_tool")
    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_resolved_model_comes_from_final_completion(
        self, mock_instructor: MagicMock, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        """The tool-loop's raw rounds use the same model but their responses
        are discarded; only the final structured-output call's completion is
        what's returned, so its .model is the one worth reporting."""
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = InstructorLLMClient(config=config)
        mock_execute_tool.return_value = '{"found": false}'

        tool_call = self._tool_call("call_1", "lookup_organization", '{"name": "X"}')
        client._raw_client.chat.completions.create.return_value = self._raw_response([tool_call])

        fake_result = SimpleOutput(name="test")
        fake_completion = MagicMock()
        fake_completion.usage = None
        fake_completion.model = "deepseek/deepseek-v4-flash-2508"
        client._instructor_client.chat.completions.create_with_completion.return_value = (
            fake_result,
            fake_completion,
        )

        _result, usage = client.complete_with_tools(
            prompt="hello", response_model=SimpleOutput, tools=["lookup_organization"], max_tool_rounds=2
        )

        assert usage.model == "deepseek/deepseek-v4-flash-2508"


class TestReaskToolsNoneCrashPatch:
    """Regression coverage for the instructor upstream bug worked around in
    instructor_client._patch_instructor_reask_tools_none_crash().

    Some providers (observed with ZAI's glm-5.2) sometimes answer with plain
    content instead of a tool call. instructor's own reask_tools() then
    crashes with TypeError('NoneType' object is not iterable) instead of
    building a retry message — this patch makes it fall back gracefully.
    """

    def test_none_tool_calls_falls_back_instead_of_crashing(self) -> None:
        from instructor.v2.providers.openai import handlers

        message = MagicMock()
        message.tool_calls = None
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]

        kwargs = {"messages": [{"role": "user", "content": "original prompt"}]}
        result = handlers.reask_tools(kwargs, response, ValueError("bad output"))

        assert len(result["messages"]) == 2
        assert result["messages"][0] == {"role": "user", "content": "original prompt"}
        assert "bad output" in result["messages"][1]["content"]
        # Original kwargs must not be mutated.
        assert len(kwargs["messages"]) == 1

    def test_present_tool_calls_keeps_original_behavior(self) -> None:
        """When tool_calls IS present, the patch must not intercept —
        instructor's normal (bug-free) tool-aware reask path still runs."""
        from instructor.v2.providers.openai import handlers

        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "SomeModel"
        message = MagicMock()
        message.tool_calls = [tool_call]
        message.function_call = None
        message.model_dump.return_value = {"role": "assistant", "tool_calls": [{"id": "call_1"}]}
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]

        kwargs = {"messages": [{"role": "user", "content": "original prompt"}]}
        result = handlers.reask_tools(kwargs, response, ValueError("bad output"))

        tool_messages = [m for m in result["messages"] if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0]["tool_call_id"] == "call_1"
