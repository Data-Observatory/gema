"""Transport-level retry/rate-limit middleware for LLM clients.

This module implements the *transport* retry layer using ``tenacity``. It wraps
any :class:`~metadata_enricher.llm.base.LLMClient` and transparently retries
calls that fail due to transient network/transport errors:

* ``openai.RateLimitError`` (HTTP 429)
* ``openai.APIStatusError`` with a status code in ``RetryConfig.retry_on_status``
  (500, 502, 503, 504 by default)
* ``openai.APITimeoutError`` / ``openai.APIConnectionError``
* ``httpx.TimeoutException`` / ``httpx.ConnectError``

It deliberately **does not** retry validation errors — those are owned by the
Instructor layer (T9) which validates structured outputs:

* ``pydantic.ValidationError``
* ``ValueError``

Client (4xx) errors other than 429 are likewise not retried, since they are
non-transient.

``instructor.exceptions.InstructorRetryException`` is a special case: Instructor
raises it both when the LLM's output is a genuine, permanent validation
dead-end (never retry — could loop forever) *and* when a transient transport
error (e.g. a sustained 429) exhausted Instructor's own internal retry budget
before this layer ever saw it. Instructor sets ``__cause__`` to the original
exception in both cases (``raise InstructorRetryException(...) from
last_exception``), so this layer unwraps it and re-checks retryability against
the *root cause* instead of blanket-rejecting every InstructorRetryException.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import httpx
import openai
import pydantic
from pydantic import BaseModel, ConfigDict
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)
from tenacity.wait import wait_base

from metadata_enricher.llm.base import LLMClient
from metadata_enricher.types import TokenUsage

if TYPE_CHECKING:
    # Avoid runtime deprecation warning from instructor.exceptions; imported
    # only for isinstance checks against the concrete exception class.
    pass

try:  # pragma: no cover - import path depends on instructor version
    from instructor.core import InstructorRetryException
except ImportError:  # pragma: no cover
    from instructor.exceptions import InstructorRetryException


# Exceptions that represent *validation* failures and must never be retried.
# The Instructor layer (T9) is responsible for retrying these.
# InstructorRetryException is NOT here — it needs special unwrapping, see
# _is_retryable below.
_NON_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    pydantic.ValidationError,
    ValueError,
)

# Transport-level exceptions that are always retryable regardless of payload.
_RETRYABLE_TRANSPORT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    httpx.TimeoutException,
    httpx.ConnectError,
)


class RetryConfig(BaseModel):
    """Configuration for the transport-level retry wrapper.

    All fields are validated at construction time. Unknown fields raise errors.
    """

    model_config = ConfigDict(extra="forbid")

    max_retries: int = 6
    """Maximum number of *retries* (so up to ``max_retries + 1`` total attempts).

    Live testing against zai-coding-plan showed sustained 429 bursts that
    outlast 3 retries' worth of backoff (a few seconds) but clear up within
    roughly a minute — a resource that exhausted the old budget failed, and
    the very next resource ran with zero 429s. 6 retries with exponential
    backoff up to max_wait gives roughly 2 more minutes of runway before
    giving up, which comfortably covers that recovery window.
    """

    initial_wait: float = 1.0
    """Multiplier for the exponential backoff (seconds)."""

    max_wait: float = 60.0
    """Upper bound for the backoff between attempts (seconds)."""

    retry_on_status: list[int] = [429, 500, 502, 503, 504]
    """HTTP status codes that should trigger a retry for ``APIStatusError``."""

    jitter: bool = True
    """When True, add a small random jitter to each backoff to avoid thundering herds."""


class RetryableLLMClient:
    """Wraps an :class:`LLMClient` adding transport-level retry/backoff.

    Satisfies the :class:`~metadata_enricher.llm.base.LLMClient` Protocol. Only
    transient transport errors are retried; validation and client (4xx≠429)
    errors propagate immediately.
    """

    def __init__(self, inner: LLMClient, config: RetryConfig | None = None) -> None:
        self._inner = inner
        self._config = config if config is not None else RetryConfig()
        self._retrying = self._build_retrying(self._config)

    @property
    def model(self) -> str:
        """Model name, delegated to the wrapped client."""
        return self._inner.model

    @property
    def inner(self) -> LLMClient:
        """The wrapped client (exposed for inspection/testing)."""
        return self._inner

    @property
    def config(self) -> RetryConfig:
        """The active retry configuration."""
        return self._config

    def complete(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> BaseModel:
        """Structured completion with transport-level retry."""
        for attempt in self._retrying:
            with attempt:
                return self._inner.complete(
                    prompt=prompt,
                    response_model=response_model,
                    system_prompt=system_prompt,
                    **kwargs,
                )
        # Unreachable: tenacity returns from inside the loop or raises with reraise=True.
        # Present so static type checkers see an explicit return path.
        raise RuntimeError("unreachable")

    def complete_raw(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        """Raw text completion with transport-level retry."""
        for attempt in self._retrying:
            with attempt:
                return self._inner.complete_raw(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    **kwargs,
                )
        raise RuntimeError("unreachable")

    def complete_with_usage(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> tuple[BaseModel, TokenUsage]:
        """Structured completion + token usage, with transport-level retry.

        Not part of the formal LLMClient Protocol — an optional, duck-typed
        extension only the real production chain (Instructor/Retryable/
        Cached) implements, so existing test mocks across the codebase never
        need to grow this method. See agents/base.py's hasattr check.
        """
        inner_with_usage = getattr(self._inner, "complete_with_usage", None)
        for attempt in self._retrying:
            with attempt:
                if inner_with_usage is not None:
                    return cast(
                        "tuple[BaseModel, TokenUsage]",
                        inner_with_usage(
                            prompt=prompt,
                            response_model=response_model,
                            system_prompt=system_prompt,
                            **kwargs,
                        ),
                    )
                result = self._inner.complete(
                    prompt=prompt,
                    response_model=response_model,
                    system_prompt=system_prompt,
                    **kwargs,
                )
                return result, TokenUsage()
        raise RuntimeError("unreachable")

    @staticmethod
    def _build_retrying(config: RetryConfig) -> Retrying:
        """Build a ``tenacity`` retry controller from a ``RetryConfig``."""
        wait: wait_base = wait_exponential(
            multiplier=config.initial_wait,
            max=config.max_wait,
        )
        if config.jitter:
            wait = wait + wait_random(0, config.initial_wait)

        return Retrying(
            stop=stop_after_attempt(config.max_retries + 1),
            wait=wait,
            retry=retry_if_exception(lambda exc: _is_retryable(exc, config.retry_on_status)),
            reraise=True,
        )


def _is_retryable(exc: BaseException, retry_on_status: list[int]) -> bool:
    """Return True if ``exc`` is a transient transport error worth retrying.

    Validation errors and non-429 client errors are *not* retryable.
    """
    # InstructorRetryException conflates two very different situations —
    # unwrap to the root cause (see module docstring) rather than guessing.
    if isinstance(exc, InstructorRetryException):
        cause = exc.__cause__
        return cause is not None and _is_retryable(cause, retry_on_status)

    # Validation errors are owned by the Instructor layer — never retry here.
    if isinstance(exc, _NON_RETRYABLE_EXCEPTIONS):
        return False

    # Always-retryable transport-level errors.
    if isinstance(exc, _RETRYABLE_TRANSPORT_EXCEPTIONS):
        return True

    # Rate limit (HTTP 429) is always transient.
    if isinstance(exc, openai.RateLimitError):
        return True

    # Other API status errors: retry only if the status code is whitelisted.
    # This covers 5xx (retryable) and rejects 4xx≠429 (e.g. 400/401/404).
    if isinstance(exc, openai.APIStatusError):
        status_code = getattr(exc, "status_code", None)
        return status_code in retry_on_status

    return False
