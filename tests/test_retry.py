"""Tests for transport-level retry middleware (metadata_enricher.llm.retry).

Uses ``unittest.mock`` and SHORT backoff waits so the suite is fast and makes no
network calls. All OpenAI/httpx exceptions are constructed directly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import openai
import pytest
from pydantic import BaseModel, ValidationError

from metadata_enricher.llm.base import LLMClient
from metadata_enricher.llm.retry import RetryConfig, RetryableLLMClient
from metadata_enricher.types import TokenUsage

try:
    from instructor.core import InstructorRetryException
except ImportError:  # pragma: no cover
    from instructor.exceptions import InstructorRetryException  # type: ignore[no-redef]


class SimpleModel(BaseModel):
    name: str = "ok"
    value: int = 1


def _fast_config() -> RetryConfig:
    return RetryConfig(max_retries=3, initial_wait=0.01, max_wait=0.05)


def _resp(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    return response


def _make_validation_error() -> ValidationError:
    class _NeedsField(BaseModel):
        x: int

    try:
        _NeedsField.model_validate({})
    except ValidationError as exc:
        return exc
    raise AssertionError("unreachable")


def _instructor_retry_exc_with_cause(cause: BaseException | None) -> InstructorRetryException:
    """Build an InstructorRetryException with __cause__ set the way instructor
    itself sets it: ``raise InstructorRetryException(...) from last_exception``.
    """
    if cause is None:
        return InstructorRetryException("failed", n_attempts=1, total_usage=0)
    try:
        raise InstructorRetryException("failed", n_attempts=1, total_usage=0) from cause
    except InstructorRetryException as exc:
        return exc


class TestSuccess:
    def test_success_on_first_try_calls_inner_once(self) -> None:
        inner = MagicMock()
        expected = SimpleModel()
        inner.complete.return_value = expected

        client = RetryableLLMClient(inner, _fast_config())
        result = client.complete("test", SimpleModel)

        assert result is expected
        assert inner.complete.call_count == 1


class TestRetriesThenSucceeds:
    @pytest.mark.parametrize(
        ("exc_factory",),
        [
            (lambda: openai.RateLimitError("429", response=_resp(429), body=None),),
            (lambda: openai.APIStatusError("500", response=_resp(500), body=None),),
            (lambda: openai.APIStatusError("503", response=_resp(503), body=None),),
            (lambda: openai.APITimeoutError(request=MagicMock()),),
            (lambda: openai.APIConnectionError(message="down", request=MagicMock()),),
            (lambda: httpx.TimeoutException("timeout"),),
            (lambda: httpx.ConnectError("nope"),),
        ],
    )
    def test_retries_on_transport_error_then_succeeds(self, exc_factory) -> None:
        inner = MagicMock()
        inner.complete.side_effect = [exc_factory(), SimpleModel()]

        client = RetryableLLMClient(inner, _fast_config())
        result = client.complete("test", SimpleModel)

        assert isinstance(result, SimpleModel)
        assert inner.complete.call_count == 2

    def test_complete_raw_also_retries_on_transport_error(self) -> None:
        inner = MagicMock()
        inner.complete_raw.side_effect = [
            openai.RateLimitError("429", response=_resp(429), body=None),
            "recovered",
        ]

        client = RetryableLLMClient(inner, _fast_config())
        result = client.complete_raw("test")

        assert result == "recovered"
        assert inner.complete_raw.call_count == 2


class TestExhaustsRetries:
    def test_fails_after_max_retries_exhausted(self) -> None:
        inner = MagicMock()
        last = openai.APIStatusError("500", response=_resp(500), body=None)
        inner.complete.side_effect = [
            openai.RateLimitError("429", response=_resp(429), body=None),
            openai.APIStatusError("502", response=_resp(502), body=None),
            last,
        ]

        client = RetryableLLMClient(
            inner, RetryConfig(max_retries=2, initial_wait=0.01, max_wait=0.05)
        )
        with pytest.raises(openai.APIStatusError) as excinfo:
            client.complete("test", SimpleModel)

        # max_retries=2 -> 3 total attempts; reraise=True surfaces the last exception.
        assert inner.complete.call_count == 3
        assert excinfo.value is last


class TestNonRetryable:
    def test_does_not_retry_on_400_bad_request(self) -> None:
        inner = MagicMock()
        inner.complete.side_effect = openai.BadRequestError("bad", response=_resp(400), body=None)

        client = RetryableLLMClient(inner, _fast_config())
        with pytest.raises(openai.BadRequestError):
            client.complete("test", SimpleModel)

        assert inner.complete.call_count == 1

    def test_does_not_retry_on_api_status_400(self) -> None:
        inner = MagicMock()
        inner.complete.side_effect = openai.APIStatusError("400", response=_resp(400), body=None)

        client = RetryableLLMClient(inner, _fast_config())
        with pytest.raises(openai.APIStatusError):
            client.complete("test", SimpleModel)

        assert inner.complete.call_count == 1

    def test_does_not_retry_on_pydantic_validation_error(self) -> None:
        inner = MagicMock()
        inner.complete.side_effect = _make_validation_error()

        client = RetryableLLMClient(inner, _fast_config())
        with pytest.raises(ValidationError):
            client.complete("test", SimpleModel)

        assert inner.complete.call_count == 1

    def test_does_not_retry_on_instructor_retry_exception(self) -> None:
        inner = MagicMock()
        inner.complete.side_effect = InstructorRetryException(
            "validation failed", n_attempts=1, total_usage=0
        )

        client = RetryableLLMClient(inner, _fast_config())
        with pytest.raises(InstructorRetryException):
            client.complete("test", SimpleModel)

        assert inner.complete.call_count == 1

    def test_does_not_retry_on_value_error(self) -> None:
        inner = MagicMock()
        inner.complete.side_effect = ValueError("boom")

        client = RetryableLLMClient(inner, _fast_config())
        with pytest.raises(ValueError):
            client.complete("test", SimpleModel)

        assert inner.complete.call_count == 1


class TestInstructorRetryExceptionUnwrapping:
    """InstructorRetryException is raised by Instructor both for genuine
    validation dead-ends AND for transport failures (e.g. sustained 429s)
    that exhausted Instructor's own internal retry budget. This layer must
    unwrap __cause__ and retry only the latter.
    """

    def test_retries_when_cause_is_rate_limit_error(self) -> None:
        rate_limit_exc = openai.RateLimitError("429", response=_resp(429), body=None)
        wrapped = _instructor_retry_exc_with_cause(rate_limit_exc)

        inner = MagicMock()
        inner.complete.side_effect = [wrapped, SimpleModel()]

        client = RetryableLLMClient(inner, _fast_config())
        result = client.complete("test", SimpleModel)

        assert isinstance(result, SimpleModel)
        assert inner.complete.call_count == 2

    def test_retries_when_cause_is_retryable_api_status_error(self) -> None:
        status_exc = openai.APIStatusError("503", response=_resp(503), body=None)
        wrapped = _instructor_retry_exc_with_cause(status_exc)

        inner = MagicMock()
        inner.complete.side_effect = [wrapped, SimpleModel()]

        client = RetryableLLMClient(inner, _fast_config())
        result = client.complete("test", SimpleModel)

        assert isinstance(result, SimpleModel)
        assert inner.complete.call_count == 2

    def test_does_not_retry_when_cause_is_validation_error(self) -> None:
        wrapped = _instructor_retry_exc_with_cause(_make_validation_error())

        inner = MagicMock()
        inner.complete.side_effect = wrapped

        client = RetryableLLMClient(inner, _fast_config())
        with pytest.raises(InstructorRetryException):
            client.complete("test", SimpleModel)

        assert inner.complete.call_count == 1

    def test_does_not_retry_when_cause_is_non_retryable_status_error(self) -> None:
        status_exc = openai.APIStatusError("400", response=_resp(400), body=None)
        wrapped = _instructor_retry_exc_with_cause(status_exc)

        inner = MagicMock()
        inner.complete.side_effect = wrapped

        client = RetryableLLMClient(inner, _fast_config())
        with pytest.raises(InstructorRetryException):
            client.complete("test", SimpleModel)

        assert inner.complete.call_count == 1

    def test_does_not_retry_when_no_cause_at_all(self) -> None:
        """No __cause__ (e.g. constructed directly, not via `raise ... from`)
        must fall back to the original, safe non-retryable behavior."""
        wrapped = _instructor_retry_exc_with_cause(None)

        inner = MagicMock()
        inner.complete.side_effect = wrapped

        client = RetryableLLMClient(inner, _fast_config())
        with pytest.raises(InstructorRetryException):
            client.complete("test", SimpleModel)

        assert inner.complete.call_count == 1


class TestProtocolAndDelegation:
    def test_model_property_delegates_to_inner(self) -> None:
        inner = MagicMock()
        inner.model = "gpt-test"

        client = RetryableLLMClient(inner, _fast_config())
        assert client.model == "gpt-test"

    def test_implements_llm_client_protocol(self) -> None:
        inner = MagicMock()
        inner.model = "gpt-test"

        client = RetryableLLMClient(inner, _fast_config())
        assert isinstance(client, LLMClient)


class TestCompleteWithUsage:
    """complete_with_usage is an optional, duck-typed extension — not part
    of the formal LLMClient Protocol (see retry.py's docstring)."""

    def test_delegates_to_inner_when_available(self) -> None:
        inner = MagicMock()
        expected_usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
        inner.complete_with_usage.return_value = (SimpleModel(), expected_usage)

        client = RetryableLLMClient(inner, _fast_config())
        result, usage = client.complete_with_usage("test", SimpleModel)

        assert isinstance(result, SimpleModel)
        assert usage is expected_usage
        assert inner.complete_with_usage.call_count == 1

    def test_falls_back_to_plain_complete_with_zero_usage_when_inner_lacks_it(self) -> None:
        inner = MagicMock()
        del inner.complete_with_usage  # simulate a client without the method
        inner.complete.return_value = SimpleModel()

        client = RetryableLLMClient(inner, _fast_config())
        result, usage = client.complete_with_usage("test", SimpleModel)

        assert result is inner.complete.return_value
        assert usage == TokenUsage()
        assert inner.complete.call_count == 1

    def test_retries_on_transport_error_then_succeeds(self) -> None:
        inner = MagicMock()
        expected_usage = TokenUsage(prompt_tokens=1)
        inner.complete_with_usage.side_effect = [
            openai.RateLimitError("429", response=_resp(429), body=None),
            (SimpleModel(), expected_usage),
        ]

        client = RetryableLLMClient(inner, _fast_config())
        result, usage = client.complete_with_usage("test", SimpleModel)

        assert isinstance(result, SimpleModel)
        assert usage is expected_usage
        assert inner.complete_with_usage.call_count == 2


class TestCustomConfig:
    def test_custom_max_retries_respected(self) -> None:
        inner = MagicMock()
        inner.complete.side_effect = [
            openai.RateLimitError("429", response=_resp(429), body=None),
            SimpleModel(),
        ]

        # max_retries=1 -> 2 total attempts: 1 failure then success on 2nd.
        client = RetryableLLMClient(
            inner, RetryConfig(max_retries=1, initial_wait=0.01, max_wait=0.05)
        )
        result = client.complete("test", SimpleModel)
        assert isinstance(result, SimpleModel)
        assert inner.complete.call_count == 2

    def test_custom_max_retries_exhausts_as_expected(self) -> None:
        inner = MagicMock()
        inner.complete.side_effect = [
            openai.RateLimitError("429", response=_resp(429), body=None),
            openai.RateLimitError("429", response=_resp(429), body=None),
        ]

        # max_retries=1 -> 2 total attempts; two consecutive failures exhaust it.
        client = RetryableLLMClient(
            inner, RetryConfig(max_retries=1, initial_wait=0.01, max_wait=0.05)
        )
        with pytest.raises(openai.RateLimitError):
            client.complete("test", SimpleModel)
        assert inner.complete.call_count == 2

    def test_custom_retry_on_status_503_only(self) -> None:
        inner = MagicMock()
        # 502 is NOT in the custom whitelist -> immediate failure.
        inner.complete.side_effect = openai.APIStatusError("502", response=_resp(502), body=None)

        client = RetryableLLMClient(
            inner,
            RetryConfig(
                max_retries=3,
                initial_wait=0.01,
                max_wait=0.05,
                retry_on_status=[503],
            ),
        )
        with pytest.raises(openai.APIStatusError):
            client.complete("test", SimpleModel)
        assert inner.complete.call_count == 1

    def test_default_config_values(self) -> None:
        rc = RetryConfig()
        assert rc.max_retries == 6
        assert rc.initial_wait == 1.0
        assert rc.max_wait == 60.0
        assert rc.retry_on_status == [429, 500, 502, 503, 504]
        assert rc.jitter is True

    def test_config_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            RetryConfig.model_validate({"unknown_field": True})


class TestKwargsForwarding:
    def test_complete_forwards_kwargs_to_inner(self) -> None:
        inner = MagicMock()
        inner.complete.return_value = SimpleModel()

        client = RetryableLLMClient(inner, _fast_config())
        client.complete("test", SimpleModel, temperature=0.7, user="abc")

        inner.complete.assert_called_once()
        _, kwargs = inner.complete.call_args
        assert kwargs["temperature"] == 0.7
        assert kwargs["user"] == "abc"
