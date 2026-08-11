"""Instructor-backed LLM client implementing LLMClient Protocol."""

from __future__ import annotations

import logging
from typing import Any, cast

import instructor
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from metadata_enricher.llm.base import LLMConfig
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
