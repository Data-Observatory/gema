"""Instructor-backed LLM client implementing LLMClient Protocol."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import instructor
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from metadata_enricher.llm.base import LLMConfig
from metadata_enricher.llm.tools import execute_tool, tool_schemas
from metadata_enricher.types import TokenUsage

logger = logging.getLogger(__name__)


def _build_extra_body(config: LLMConfig) -> dict[str, Any] | None:
    """Merge seed (OpenAI SDK requires it in extra_body, not top-level) with
    any provider/model-specific overrides from config.extra_body."""
    extra_body: dict[str, Any] = {}
    if config.seed is not None:
        extra_body["seed"] = config.seed
    if config.extra_body:
        extra_body.update(config.extra_body)
    return extra_body or None


def _patch_instructor_reask_tools_none_crash() -> None:
    """Work around a crash in instructor's TOOLS-mode retry-repair path.

    Some OpenAI-compatible providers (observed with ZAI's glm-5.2) sometimes
    ignore a forced ``tool_choice`` and answer with plain ``message.content``
    instead of a tool call. instructor correctly detects this and raises
    ``ResponseParsingError("No tool calls or function call found...")``, then
    tries to build a "please retry" reask message via
    ``reask_tools()`` (instructor.v2.providers.openai.handlers) — which
    unconditionally does ``for tool_call in response.choices[0].message.tool_calls``
    with no None-guard. Since ``tool_calls`` is exactly what's missing, this
    raises a bare ``TypeError: 'NoneType' object is not iterable'`` that
    masks the original error and aborts after 1 attempt instead of asking
    the model to retry.

    Confirmed present in instructor 1.15.3 and 1.15.4 (latest at time of
    writing) — no upstream fix yet. This patches only the None-tool_calls
    branch; the normal (bug-free) path is untouched. Safe to delete once
    fixed upstream.
    """
    from instructor.v2.providers.openai import handlers as _openai_handlers

    _original_reask_tools = _openai_handlers.reask_tools

    def _reask_tools_none_safe(
        kwargs: dict[str, Any], response: Any, exception: Exception
    ) -> dict[str, Any]:
        message = response.choices[0].message
        if not getattr(message, "tool_calls", None):
            logger.debug(
                "Model answered without a tool call; falling back to a plain "
                "reask message instead of crashing (see "
                "_patch_instructor_reask_tools_none_crash)."
            )
            patched_kwargs = kwargs.copy()
            patched_kwargs["messages"] = [
                *kwargs["messages"],
                {
                    "role": "user",
                    "content": (
                        f"Validation Error found:\n{exception}\n"
                        "Recall the function correctly, fix the errors"
                    ),
                },
            ]
            return patched_kwargs
        # _original_reask_tools is untyped (third-party, no stubs) — cast the
        # known-correct return shape rather than letting Any leak out.
        return cast("dict[str, Any]", _original_reask_tools(kwargs, response, exception))

    _openai_handlers.reask_tools = _reask_tools_none_safe


_patch_instructor_reask_tools_none_crash()


class InstructorLLMClient:
    """LLM client using Instructor for structured outputs.

    Implements the LLMClient Protocol with an Instructor-wrapped OpenAI client
    for validated Pydantic responses and a raw OpenAI client for text-only
    completions.
    """

    def __init__(self, config: LLMConfig, max_retries: int = 3) -> None:
        self._config = config
        self._max_retries = max_retries

        raw_client_kwargs: dict[str, Any] = {
            "api_key": config.api_key.get_secret_value(),
            "timeout": config.timeout,
        }
        if config.base_url is not None:
            raw_client_kwargs["base_url"] = config.base_url

        raw_client = OpenAI(**raw_client_kwargs)
        self._instructor_client = instructor.from_openai(raw_client)
        self._raw_client = raw_client

    @property
    def model(self) -> str:
        """Return the configured model name."""
        return self._config.model

    def complete(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> BaseModel:
        """Send prompt and return a validated Pydantic object."""
        messages: list[dict[str, Any]] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        create_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "response_model": response_model,
            "messages": messages,
            "max_retries": self._max_retries,
            "temperature": self._config.temperature,
        }
        if self._config.max_tokens is not None:
            create_kwargs["max_tokens"] = self._config.max_tokens
        extra_body = _build_extra_body(self._config)
        if extra_body is not None:
            create_kwargs["extra_body"] = extra_body
        create_kwargs.update(kwargs)

        # instructor's create() return type can't be inferred through a
        # **dict[str, Any] spread; response_model guarantees a BaseModel.
        return cast(BaseModel, self._instructor_client.chat.completions.create(**create_kwargs))

    def complete_with_usage(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> tuple[BaseModel, TokenUsage]:
        """Same as complete(), plus real token usage from the provider's
        response. Uses instructor's create_with_completion() (returns the
        parsed model *and* the raw completion instructor's plain create()
        discards) instead of duplicating the request — one API call either
        way. Not part of the formal LLMClient Protocol; see retry.py's
        complete_with_usage for why."""
        messages: list[dict[str, Any]] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        create_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "response_model": response_model,
            "messages": messages,
            "max_retries": self._max_retries,
            "temperature": self._config.temperature,
        }
        if self._config.max_tokens is not None:
            create_kwargs["max_tokens"] = self._config.max_tokens
        extra_body = _build_extra_body(self._config)
        if extra_body is not None:
            create_kwargs["extra_body"] = extra_body
        create_kwargs.update(kwargs)

        result, completion = self._instructor_client.chat.completions.create_with_completion(
            **create_kwargs
        )
        usage = getattr(completion, "usage", None)
        token_usage = (
            TokenUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
            )
            if usage is not None
            else TokenUsage()
        )
        return cast(BaseModel, result), token_usage

    def complete_with_tools(
        self,
        prompt: str,
        response_model: type[BaseModel],
        tools: list[str],
        system_prompt: str | None = None,
        max_tool_rounds: int = 2,
        **kwargs: Any,
    ) -> tuple[BaseModel, TokenUsage]:
        """Agentic tool-call loop, then a final forced structured-output call.

        Not part of the formal LLMClient Protocol -- an optional, duck-typed
        extension only agents that declare ``tools:`` in config ever request
        (see agents/base.py's hasattr check), same pattern as
        complete_with_usage.

        Sends an initial turn with ``tools=`` and ``tool_choice="auto"``
        (unforced -- it's the *forced* tool_choice used by the final
        structured-output call below that some providers reject alongside
        their default "thinking mode", see _build_extra_body's docstring; an
        unforced auto tool_choice has no such issue). If the model calls any
        tool, executes it via llm.tools.execute_tool and records the result,
        repeating up to *max_tool_rounds* times.

        The final structured-output call does NOT reuse the raw tool-call
        loop's message history verbatim -- it gets a fresh [system?, user]
        pair plus one plain-text user note summarizing any tool calls/results
        (only appended if at least one tool was actually called). This was a
        deliberate fix (2026-08-15) for a real regression found piloting this
        loop on creators_publishers/deepseek-v4-flash: when a round-capped
        conversation's raw tool_calls/tool-role messages were fed straight
        into the final call, the model would sometimes return empty
        creators/publishers instead of its actual extraction -- likely
        confused by a forced tool_choice (Instructor's synthetic
        response-model tool) following assistant turns that reference a
        different, now-undeclared tool. Collapsing the tool exchange into
        plain text before the final call sidesteps that entirely and is
        portable across providers, at the cost of the model re-reading a
        summary instead of the raw exchange (no evidence this loses
        information in practice -- the summary includes every call/result).

        Token usage is summed across every round (including the final call)
        -- a tool loop's real cost is every round combined, not just the last.
        """
        base_messages: list[dict[str, Any]] = []
        if system_prompt is not None:
            base_messages.append({"role": "system", "content": system_prompt})
        base_messages.append({"role": "user", "content": prompt})

        loop_messages: list[dict[str, Any]] = list(base_messages)
        tool_exchange_log: list[tuple[str, str, str]] = []

        extra_body = _build_extra_body(self._config)
        schemas = tool_schemas(tools)
        total_usage = TokenUsage()

        for round_num in range(max_tool_rounds):
            raw_kwargs: dict[str, Any] = {
                "model": self._config.model,
                "messages": loop_messages,
                "temperature": self._config.temperature,
                "tools": schemas,
                "tool_choice": "auto",
            }
            if self._config.max_tokens is not None:
                raw_kwargs["max_tokens"] = self._config.max_tokens
            if extra_body is not None:
                raw_kwargs["extra_body"] = extra_body
            response = self._raw_client.chat.completions.create(**raw_kwargs)
            usage = getattr(response, "usage", None)
            if usage is not None:
                total_usage = TokenUsage(
                    prompt_tokens=total_usage.prompt_tokens + (usage.prompt_tokens or 0),
                    completion_tokens=(
                        total_usage.completion_tokens + (usage.completion_tokens or 0)
                    ),
                    total_tokens=total_usage.total_tokens + (usage.total_tokens or 0),
                )
            message = response.choices[0].message
            if not message.tool_calls:
                logger.debug(
                    "Tool loop round %d: model stopped calling tools.", round_num + 1
                )
                break

            loop_messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                        for tool_call in message.tool_calls
                    ],
                }
            )
            for tool_call in message.tool_calls:
                arguments_raw = tool_call.function.arguments or "{}"
                result = execute_tool(tool_call.function.name, json.loads(arguments_raw))
                loop_messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": result}
                )
                tool_exchange_log.append((tool_call.function.name, arguments_raw, result))
        else:
            logger.warning(
                "Tool loop hit max_tool_rounds=%d without the model stopping tool "
                "calls; proceeding to the final structured-output call anyway.",
                max_tool_rounds,
            )

        final_messages = list(base_messages)
        if tool_exchange_log:
            summary_lines = [
                f"- {name}({args}) -> {result}"
                for name, args, result in tool_exchange_log
            ]
            final_messages.append(
                {
                    "role": "user",
                    "content": (
                        "During your reasoning you looked up the following via tool "
                        "calls -- use these results if relevant to your final answer:\n"
                        + "\n".join(summary_lines)
                    ),
                }
            )

        create_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "response_model": response_model,
            "messages": final_messages,
            "max_retries": self._max_retries,
            "temperature": self._config.temperature,
        }
        if self._config.max_tokens is not None:
            create_kwargs["max_tokens"] = self._config.max_tokens
        if extra_body is not None:
            create_kwargs["extra_body"] = extra_body
        create_kwargs.update(kwargs)

        result, completion = self._instructor_client.chat.completions.create_with_completion(
            **create_kwargs
        )
        final_usage = getattr(completion, "usage", None)
        if final_usage is not None:
            total_usage = TokenUsage(
                prompt_tokens=total_usage.prompt_tokens + (final_usage.prompt_tokens or 0),
                completion_tokens=(
                    total_usage.completion_tokens + (final_usage.completion_tokens or 0)
                ),
                total_tokens=total_usage.total_tokens + (final_usage.total_tokens or 0),
            )
        return cast(BaseModel, result), total_usage

    def complete_raw(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Send prompt and return raw text response."""
        messages: list[dict[str, Any]] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        extra_kwargs: dict[str, Any] = {}
        extra_body = _build_extra_body(self._config)
        if extra_body is not None:
            extra_kwargs["extra_body"] = extra_body
        response = self._raw_client.chat.completions.create(
            model=self._config.model,
            messages=cast("list[ChatCompletionMessageParam]", messages),
            temperature=self._config.temperature,
            **extra_kwargs,
            **kwargs,
        )
        return response.choices[0].message.content or ""
