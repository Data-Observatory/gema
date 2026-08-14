"""LLM abstraction layer — Protocol and configuration."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, SecretStr


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM client implementations.

    Defines the interface for structured (Instructor-style) and raw LLM completions.
    Implementations like InstructorLLMClient (T9) will satisfy this protocol.
    """

    @property
    def model(self) -> str:
        """Returns the model name being used."""

    def complete(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> BaseModel:
        """Send prompt and return a validated Pydantic object.

        Args:
            prompt: The user prompt text.
            response_model: Pydantic model class for structured output.
            system_prompt: Optional system-level instructions.
            **kwargs: Additional provider-specific parameters.

        Returns:
            A validated instance of response_model.
        """

    def complete_raw(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        """Send prompt and return raw text response.

        Args:
            prompt: The user prompt text.
            system_prompt: Optional system-level instructions.
            **kwargs: Additional provider-specific parameters.

        Returns:
            Raw text response from the LLM.
        """


class LLMConfig(BaseModel):
    """Configuration for LLM client connections.

    All fields are validated at construction time. Unknown fields raise errors.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    api_key: SecretStr
    base_url: str | None = None
    temperature: float = 0.0
    seed: int | None = None
    max_tokens: int | None = None
    timeout: float = 240.0
    extra_body: dict[str, Any] | None = None
