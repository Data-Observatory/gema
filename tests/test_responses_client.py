"""Tests for ResponsesLLMClient (OpenAI Responses API structured output)."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from metadata_enricher.llm.base import LLMClient, LLMConfig
from metadata_enricher.llm.responses_client import (
    ResponsesLLMClient,
    _extract_json,
    _to_responses_tool_schema,
)
from metadata_enricher.llm.retry import _is_retryable


class SimpleOutput(BaseModel):
    """Simple response model for testing."""

    name: str


def _response(
    output_text: str | None = "",
    status: str = "completed",
    usage: Any = None,
    model: str = "resolved-model",
    output: list[Any] | None = None,
    incomplete_details: Any = None,
) -> SimpleNamespace:
    """Build a fake ``openai.types.responses.Response``-shaped object.
    Only the attributes this client actually reads via getattr()."""
    return SimpleNamespace(
        output_text=output_text,
        status=status,
        usage=usage,
        model=model,
        output=output or [],
        incomplete_details=incomplete_details,
    )


def _usage(input_tokens: int = 10, output_tokens: int = 5, total_tokens: int = 15) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        output_tokens_details=SimpleNamespace(reasoning_tokens=0),
    )


def _function_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(type="function_call", call_id=call_id, name=name, arguments=arguments)


class TestConstruction:
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_constructor_without_base_url(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)

        mock_openai.assert_called_once_with(api_key="sk-test", timeout=240.0)
        assert client._config is config
        assert client.model == "my-model"

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_constructor_with_base_url(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test", base_url="https://custom.api.com")
        ResponsesLLMClient(config=config)

        mock_openai.assert_called_once_with(
            api_key="sk-test", timeout=240.0, base_url="https://custom.api.com"
        )

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_protocol_conformance(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        assert isinstance(client, LLMClient)
        assert callable(client.complete)
        assert callable(client.complete_raw)
        assert callable(client.complete_with_usage)
        assert callable(client.complete_with_tools)

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_seed_set_warns_and_never_forwarded(
        self, mock_openai: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test", seed=42)
        with caplog.at_level("WARNING"):
            client = ResponsesLLMClient(config=config)
        assert any("seed" in record.message for record in caplog.records)

        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )
        client.complete(prompt="hello", response_model=SimpleOutput)
        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert "seed" not in call_kwargs
        extra_body = call_kwargs.get("extra_body")
        assert not extra_body or "seed" not in extra_body

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_extra_body_thinking_filtered_and_warns(
        self, mock_openai: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = LLMConfig(
            model="my-model",
            api_key="sk-test",
            extra_body={"thinking": {"type": "disabled"}, "keep_me": "yes"},
        )
        with caplog.at_level("WARNING"):
            client = ResponsesLLMClient(config=config)
            client._raw_client.responses.create.return_value = _response(
                output_text='{"name": "x"}', usage=_usage()
            )
            client.complete(prompt="hello", response_model=SimpleOutput)

        assert any("thinking" in record.message for record in caplog.records)
        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"keep_me": "yes"}


class TestRequestShaping:
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_input_shape_with_system_prompt(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )
        client.complete(prompt="hi", response_model=SimpleOutput, system_prompt="be nice")
        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert call_kwargs["input"] == [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "hi"},
        ]

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_input_shape_without_system_prompt(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )
        client.complete(prompt="hi", response_model=SimpleOutput)
        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert call_kwargs["input"] == [{"role": "user", "content": "hi"}]

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_text_format_shape(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )
        client.complete(prompt="hi", response_model=SimpleOutput)
        text = client._raw_client.responses.create.call_args.kwargs["text"]
        assert text["format"]["type"] == "json_schema"
        assert text["format"]["strict"] is True
        assert text["format"]["name"] == "SimpleOutput"

    def test_schema_dependency_canary(self) -> None:
        """Pins openai.lib._pydantic.to_strict_json_schema's actual output
        shape -- a future openai bump silently changing the transform (e.g.
        dropping additionalProperties:false) would be caught here before it
        ever reached a real 400 from the API."""
        from openai.lib._pydantic import to_strict_json_schema

        schema = to_strict_json_schema(SimpleOutput)

        def _check(node: dict[str, Any]) -> None:
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                properties = node.get("properties", {})
                assert set(node.get("required", [])) == set(properties.keys())
                for value in properties.values():
                    if isinstance(value, dict):
                        _check(value)

        _check(schema)

    @pytest.mark.parametrize(
        ("effort", "expected"),
        [
            ("low", {"effort": "low"}),
            ("medium", {"effort": "medium"}),
            ("high", {"effort": "high"}),
            ("provider_default", None),
            (None, None),
        ],
    )
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_reasoning_block_presence(
        self, mock_openai: MagicMock, effort: str | None, expected: dict[str, str] | None
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test", reasoning_effort=effort)
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )
        client.complete(prompt="hi", response_model=SimpleOutput)
        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert call_kwargs.get("reasoning") == expected

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_temperature_always_sent_max_output_tokens_only_when_set(
        self, mock_openai: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test", temperature=0.3)
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )
        client.complete(prompt="hi", response_model=SimpleOutput)
        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3
        assert "max_output_tokens" not in call_kwargs
        assert "max_tokens" not in call_kwargs

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_max_output_tokens_sent_when_configured(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test", max_tokens=500)
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )
        client.complete(prompt="hi", response_model=SimpleOutput)
        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert call_kwargs["max_output_tokens"] == 500
        assert "max_tokens" not in call_kwargs

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_no_tool_choice_when_no_tools(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )
        client.complete(prompt="hi", response_model=SimpleOutput)
        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert "tool_choice" not in call_kwargs
        assert "tools" not in call_kwargs

    @patch("metadata_enricher.llm.responses_client.execute_tool")
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_tool_choice_is_auto_when_tools_present(
        self, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.side_effect = [
            _response(output_text="", status="completed", usage=_usage(), output=[]),
            _response(output_text='{"name": "x"}', usage=_usage()),
        ]
        client.complete_with_tools(
            prompt="hi", response_model=SimpleOutput, tools=["lookup_organization"]
        )
        first_call_kwargs = client._raw_client.responses.create.call_args_list[0].kwargs
        assert first_call_kwargs["tool_choice"] == "auto"
        assert isinstance(first_call_kwargs["tools"], list)


class TestStructuredOutputAndReask:
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_first_try_success(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "Alice"}', usage=_usage()
        )
        result = client.complete(prompt="hi", response_model=SimpleOutput)
        assert result == SimpleOutput(name="Alice")
        assert client._raw_client.responses.create.call_count == 1

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_invalid_then_valid_reasks_once(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config, max_retries=3)
        client._raw_client.responses.create.side_effect = [
            _response(output_text='{"wrong_field": "oops"}', usage=_usage()),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]
        result = client.complete(prompt="hi", response_model=SimpleOutput)
        assert result == SimpleOutput(name="Alice")
        assert client._raw_client.responses.create.call_count == 2

        second_call_input = client._raw_client.responses.create.call_args_list[1].kwargs["input"]
        assert second_call_input[-2] == {
            "role": "assistant",
            "content": '{"wrong_field": "oops"}',
        }
        assert second_call_input[-1]["role"] == "user"
        assert "name" in second_call_input[-1]["content"]

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_all_attempts_fail_raises_real_validation_error(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config, max_retries=3)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"wrong_field": "oops"}', usage=_usage()
        )
        with pytest.raises(ValidationError) as exc_info:
            client.complete(prompt="hi", response_model=SimpleOutput)
        assert client._raw_client.responses.create.call_count == 3
        assert _is_retryable(exc_info.value, [429, 500, 502, 503, 504]) is False

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_max_retries_one_means_exactly_one_call(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config, max_retries=1)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"wrong_field": "oops"}', usage=_usage()
        )
        with pytest.raises(ValidationError):
            client.complete(prompt="hi", response_model=SimpleOutput)
        assert client._raw_client.responses.create.call_count == 1

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_fenced_json_parses_in_one_call(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='```json\n{"name": "Alice"}\n```', usage=_usage()
        )
        result = client.complete(prompt="hi", response_model=SimpleOutput)
        assert result == SimpleOutput(name="Alice")
        assert client._raw_client.responses.create.call_count == 1

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_empty_output_text_triggers_reask(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config, max_retries=2)
        client._raw_client.responses.create.side_effect = [
            _response(output_text="", usage=_usage()),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]
        result = client.complete(prompt="hi", response_model=SimpleOutput)
        assert result == SimpleOutput(name="Alice")
        assert client._raw_client.responses.create.call_count == 2
        second_call_input = client._raw_client.responses.create.call_args_list[1].kwargs["input"]
        assert "empty" in second_call_input[-1]["content"].lower()
        # Regression: no empty {"role": "assistant", "content": ""} turn --
        # some OpenAI-compatible endpoints reject empty message content
        # with a 400, which would break the very reask meant to recover
        # from this failure.
        assert not any(item.get("content") == "" for item in second_call_input)

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_status_incomplete_raises_immediately(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config, max_retries=3)
        client._raw_client.responses.create.return_value = _response(
            output_text="",
            status="incomplete",
            usage=_usage(),
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        )
        with pytest.raises(ValueError, match="max_output_tokens"):
            client.complete(prompt="hi", response_model=SimpleOutput)
        assert client._raw_client.responses.create.call_count == 1

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_no_reask_input_ever_contains_reasoning_item(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config, max_retries=3)
        client._raw_client.responses.create.side_effect = [
            _response(output_text='{"wrong_field": "oops"}', usage=_usage()),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]
        client.complete(prompt="hi", response_model=SimpleOutput)
        for call in client._raw_client.responses.create.call_args_list:
            for item in call.kwargs["input"]:
                assert item.get("type") != "reasoning"


class TestUsage:
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_field_name_mapping(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "Alice"}',
            usage=_usage(input_tokens=42, output_tokens=8, total_tokens=50),
            model="resolved-model-x",
        )
        _result, usage = client.complete_with_usage(prompt="hi", response_model=SimpleOutput)
        assert usage.prompt_tokens == 42
        assert usage.completion_tokens == 8
        assert usage.total_tokens == 50
        assert usage.model == "resolved-model-x"

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_usage_summed_across_reask_attempts(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config, max_retries=3)
        client._raw_client.responses.create.side_effect = [
            _response(
                output_text='{"wrong_field": "oops"}',
                usage=_usage(input_tokens=10, output_tokens=10, total_tokens=20),
            ),
            _response(
                output_text='{"name": "Alice"}',
                usage=_usage(input_tokens=20, output_tokens=5, total_tokens=25),
            ),
        ]
        _result, usage = client.complete_with_usage(prompt="hi", response_model=SimpleOutput)
        assert usage.prompt_tokens == 30
        assert usage.completion_tokens == 15
        assert usage.total_tokens == 45

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_complete_returns_bare_model_not_tuple(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "Alice"}', usage=_usage()
        )
        result = client.complete(prompt="hi", response_model=SimpleOutput)
        assert isinstance(result, SimpleOutput)


class TestToolSchemaReshape:
    def test_flat_shape(self) -> None:
        nested = {
            "type": "function",
            "function": {
                "name": "lookup_organization",
                "description": "look it up",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        flat = _to_responses_tool_schema(nested)
        assert flat == {
            "type": "function",
            "name": "lookup_organization",
            "description": "look it up",
            "parameters": {"type": "object", "properties": {}},
        }
        assert "function" not in flat


class TestSessionHeader:
    """ResponsesLLMClient must send OpenCode's required x-opencode-session
    header exactly like InstructorLLMClient does (see that client's own
    TestSessionHeader in test_instructor_client.py) -- fresh ID per
    top-level call, absent when unset, one shared ID across a tool loop's
    rounds plus its final call. Regression coverage: this client shipped
    with no session_header support at all until this test file added it."""

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_complete_sends_extra_headers_when_configured(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(
            model="my-model", api_key="sk-test", session_header="x-opencode-session"
        )
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )

        client.complete(prompt="hello", response_model=SimpleOutput)

        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert "x-opencode-session" in call_kwargs["extra_headers"]
        assert call_kwargs["extra_headers"]["x-opencode-session"]

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_complete_omits_extra_headers_when_not_configured(
        self, mock_openai: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )

        client.complete(prompt="hello", response_model=SimpleOutput)

        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert "extra_headers" not in call_kwargs

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_separate_calls_get_different_ids(self, mock_openai: MagicMock) -> None:
        config = LLMConfig(
            model="my-model", api_key="sk-test", session_header="x-opencode-session"
        )
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(
            output_text='{"name": "x"}', usage=_usage()
        )

        client.complete(prompt="first", response_model=SimpleOutput)
        first_id = client._raw_client.responses.create.call_args.kwargs["extra_headers"][
            "x-opencode-session"
        ]
        client.complete(prompt="second", response_model=SimpleOutput)
        second_id = client._raw_client.responses.create.call_args.kwargs["extra_headers"][
            "x-opencode-session"
        ]

        assert first_id != second_id

    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_complete_raw_sends_extra_headers_when_configured(
        self, mock_openai: MagicMock
    ) -> None:
        config = LLMConfig(
            model="my-model", api_key="sk-test", session_header="x-opencode-session"
        )
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.return_value = _response(output_text="hi")

        client.complete_raw(prompt="hello")

        call_kwargs = client._raw_client.responses.create.call_args.kwargs
        assert "x-opencode-session" in call_kwargs["extra_headers"]

    @patch("metadata_enricher.llm.responses_client.execute_tool")
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_complete_with_tools_reuses_same_id_across_rounds_and_final_call(
        self, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        """One tool loop is one conversation, even across several HTTP
        requests -- every round plus the final call must share one ID."""
        config = LLMConfig(
            model="my-model", api_key="sk-test", session_header="x-opencode-session"
        )
        client = ResponsesLLMClient(config=config)
        mock_execute_tool.return_value = "{}"

        call = _function_call("call_1", "lookup_organization", "{}")
        client._raw_client.responses.create.side_effect = [
            _response(output_text="", status="completed", usage=_usage(), output=[call]),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]

        client.complete_with_tools(
            prompt="hello", response_model=SimpleOutput, tools=["lookup_organization"],
            max_tool_rounds=1,
        )

        round_ids = [
            call.kwargs["extra_headers"]["x-opencode-session"]
            for call in client._raw_client.responses.create.call_args_list
        ]
        assert len(round_ids) == 2
        assert round_ids[0] == round_ids[1]


class TestCompleteWithTools:
    @patch("metadata_enricher.llm.responses_client.execute_tool")
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_malformed_tool_arguments_do_not_crash_the_loop(
        self, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        """Regression: malformed JSON tool-call arguments from the model
        must feed an error back as the tool result, not raise out of the
        tool loop and abort the whole agent call."""
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)

        call = _function_call("call_1", "lookup_organization", "{not valid json")
        client._raw_client.responses.create.side_effect = [
            _response(output_text="", status="completed", usage=_usage(), output=[call]),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]

        result, _usage_result = client.complete_with_tools(
            prompt="hi", response_model=SimpleOutput, tools=["lookup_organization"],
            max_tool_rounds=1,
        )

        assert result == SimpleOutput(name="Alice")
        mock_execute_tool.assert_not_called()

    @patch("metadata_enricher.llm.responses_client.execute_tool")
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_tool_executor_exception_does_not_crash_the_loop(
        self, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        """Regression: an exception raised by a tool's own executor (e.g. a
        network error in lookup_organization) must feed an error back as
        the tool result, not raise out of the tool loop."""
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        mock_execute_tool.side_effect = RuntimeError("boom")

        call = _function_call("call_1", "lookup_organization", '{"name": "X"}')
        client._raw_client.responses.create.side_effect = [
            _response(output_text="", status="completed", usage=_usage(), output=[call]),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]

        result, _usage_result = client.complete_with_tools(
            prompt="hi", response_model=SimpleOutput, tools=["lookup_organization"],
            max_tool_rounds=1,
        )

        assert result == SimpleOutput(name="Alice")

    @patch("metadata_enricher.llm.responses_client.execute_tool")
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_tool_call_executed_and_fed_back(
        self, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        mock_execute_tool.return_value = '{"found": true, "canonical_name": "U de Chile"}'

        call = _function_call("call_1", "lookup_organization", '{"name": "U de Chile"}')
        client._raw_client.responses.create.side_effect = [
            _response(output_text="", status="completed", usage=_usage(), output=[call]),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]

        result, _usage_result = client.complete_with_tools(
            prompt="hi", response_model=SimpleOutput, tools=["lookup_organization"],
            max_tool_rounds=1,
        )

        assert result == SimpleOutput(name="Alice")
        mock_execute_tool.assert_called_once_with("lookup_organization", {"name": "U de Chile"})

        round2_input = client._raw_client.responses.create.call_args_list[1].kwargs
        # This is the FINAL call (no tools/tool_choice), which gets a fresh
        # input, not the raw tool loop's input.
        assert "tools" not in round2_input
        assert "tool_choice" not in round2_input
        assert "text" in round2_input

    @patch("metadata_enricher.llm.responses_client.execute_tool")
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_round1_input_gets_function_call_and_output_items(
        self, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        mock_execute_tool.return_value = '{"found": false}'

        call = _function_call("call_1", "lookup_organization", '{"name": "X"}')
        responses = [
            _response(output_text="", status="completed", usage=_usage(), output=[call]),
            _response(output_text="", status="completed", usage=_usage(), output=[]),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]
        client._raw_client.responses.create.side_effect = responses

        client.complete_with_tools(
            prompt="hi", response_model=SimpleOutput, tools=["lookup_organization"],
            max_tool_rounds=3,
        )

        # Round 2's input carries round 1's function_call + function_call_output.
        round2_call_kwargs = client._raw_client.responses.create.call_args_list[1].kwargs
        round2_input = round2_call_kwargs["input"]
        function_call_items = [i for i in round2_input if i.get("type") == "function_call"]
        output_items = [i for i in round2_input if i.get("type") == "function_call_output"]
        assert len(function_call_items) == 1
        assert function_call_items[0]["call_id"] == "call_1"
        assert function_call_items[0]["name"] == "lookup_organization"
        assert len(output_items) == 1
        assert output_items[0]["call_id"] == "call_1"
        assert output_items[0]["output"] == '{"found": false}'

    @patch("metadata_enricher.llm.responses_client.execute_tool")
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_final_call_input_is_fresh_with_summary_when_tool_ran(
        self, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        mock_execute_tool.return_value = '{"found": false}'

        call = _function_call("call_1", "lookup_organization", '{"name": "X"}')
        client._raw_client.responses.create.side_effect = [
            _response(output_text="", status="completed", usage=_usage(), output=[call]),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]

        client.complete_with_tools(
            prompt="hi", response_model=SimpleOutput, tools=["lookup_organization"],
            max_tool_rounds=1,
        )

        final_input = client._raw_client.responses.create.call_args_list[-1].kwargs["input"]
        assert final_input[0] == {"role": "user", "content": "hi"}
        assert len(final_input) == 2
        assert final_input[1]["role"] == "user"
        assert "lookup_organization" in final_input[1]["content"]
        assert not any(i.get("type") in ("function_call", "function_call_output") for i in final_input)

    @patch("metadata_enricher.llm.responses_client.execute_tool")
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_no_summary_turn_when_no_tool_called(
        self, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        client._raw_client.responses.create.side_effect = [
            _response(output_text="", status="completed", usage=_usage(), output=[]),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]

        client.complete_with_tools(
            prompt="hi", response_model=SimpleOutput, tools=["lookup_organization"]
        )
        mock_execute_tool.assert_not_called()

        final_input = client._raw_client.responses.create.call_args_list[-1].kwargs["input"]
        assert final_input == [{"role": "user", "content": "hi"}]

    @patch("metadata_enricher.llm.responses_client.execute_tool")
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_max_tool_rounds_exhaustion_logs_warning_and_still_answers(
        self,
        mock_openai: MagicMock,
        mock_execute_tool: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        mock_execute_tool.return_value = '{"found": false}'
        call = _function_call("call_1", "lookup_organization", '{"name": "X"}')
        client._raw_client.responses.create.side_effect = [
            _response(output_text="", status="completed", usage=_usage(), output=[call]),
            _response(output_text="", status="completed", usage=_usage(), output=[call]),
            _response(output_text='{"name": "Alice"}', usage=_usage()),
        ]

        with caplog.at_level("WARNING"):
            result, _usage_result = client.complete_with_tools(
                prompt="hi",
                response_model=SimpleOutput,
                tools=["lookup_organization"],
                max_tool_rounds=2,
            )

        assert result == SimpleOutput(name="Alice")
        assert any("max_tool_rounds" in record.message for record in caplog.records)

    @patch("metadata_enricher.llm.responses_client.execute_tool")
    @patch("metadata_enricher.llm.responses_client.OpenAI")
    def test_usage_summed_across_rounds_and_final_call(
        self, mock_openai: MagicMock, mock_execute_tool: MagicMock
    ) -> None:
        config = LLMConfig(model="my-model", api_key="sk-test")
        client = ResponsesLLMClient(config=config)
        mock_execute_tool.return_value = '{"found": false}'
        call = _function_call("call_1", "lookup_organization", '{"name": "X"}')
        client._raw_client.responses.create.side_effect = [
            _response(
                output_text="", status="completed",
                usage=_usage(input_tokens=10, output_tokens=10, total_tokens=20), output=[call],
            ),
            _response(
                output_text='{"name": "Alice"}',
                usage=_usage(input_tokens=5, output_tokens=5, total_tokens=10),
            ),
        ]

        _result, usage = client.complete_with_tools(
            prompt="hi", response_model=SimpleOutput, tools=["lookup_organization"],
            max_tool_rounds=1,
        )
        assert usage.prompt_tokens == 15
        assert usage.completion_tokens == 15
        assert usage.total_tokens == 30


class TestExtractJson:
    def test_already_json(self) -> None:
        assert _extract_json('{"a": 1}') == '{"a": 1}'

    def test_fenced(self) -> None:
        assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_slice_from_braces(self) -> None:
        assert _extract_json('here is your answer: {"a": 1} thanks') == '{"a": 1}'


@pytest.mark.live
class TestLiveResponsesApi:
    """One real API call against opencode:muse-spark-1.3-contributor,
    tiny/cheap by design -- the executable record of this branch's probes.
    Skippable via `pytest -m "not live"`; run manually, not wired into CI."""

    def test_real_strict_schema_round_trip(self) -> None:
        from pydantic import SecretStr

        api_key = os.environ.get("OPENCODE_API_KEY")
        if not api_key:
            pytest.skip("OPENCODE_API_KEY not set")

        config = LLMConfig(
            model="muse-spark-1.3-contributor",
            api_key=SecretStr(api_key),
            base_url="https://opencode.ai/zen/go/v1",
            reasoning_effort="medium",
            session_header="x-opencode-session",
        )
        client = ResponsesLLMClient(config=config)
        result = client.complete(
            prompt="What is the capital of France? Answer in one word.",
            response_model=SimpleOutput,
            system_prompt=(
                "Extract the answer into the 'name' field of the given JSON schema."
            ),
        )
        assert isinstance(result, SimpleOutput)
        assert "paris" in result.name.lower()
