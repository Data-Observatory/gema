"""Instructor-backed LLM client implementing LLMClient Protocol."""

from __future__ import annotations

import logging
from typing import Any

import instructor
from openai import OpenAI
from pydantic import BaseModel

from metadata_enricher.llm.base import LLMConfig

logger = logging.getLogger(__name__)


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
        create_kwargs.update(kwargs)

        return self._instructor_client.chat.completions.create(**create_kwargs)

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

        response = self._raw_client.chat.completions.create(
            model=self._config.model,
            messages=messages,
            temperature=self._config.temperature,
            **kwargs,
        )
        return response.choices[0].message.content or ""
