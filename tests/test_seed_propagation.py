"""Tests for seed and temperature propagation to LLM API calls."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from metadata_enricher.cache import CachedLLMClient, CacheManager
from metadata_enricher.llm.base import LLMClient, LLMConfig
from metadata_enricher.llm.instructor_client import InstructorLLMClient
from metadata_enricher.llm.retry import RetryConfig, RetryableLLMClient


class SimpleOutput(BaseModel):
    """Simple response model for testing."""

    name: str


# ---------------------------------------------------------------------------
# Seed propagation through InstructorLLMClient
# ---------------------------------------------------------------------------


class TestSeedPropagation:
    """Tests for seed propagation in InstructorLLMClient and cache layers."""

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_passes_seed_in_extra_body(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete() passes seed=42 via extra_body when LLMConfig.seed is set."""
        config = LLMConfig(model="gpt-4", api_key="sk-test", seed=42)
        client = InstructorLLMClient(config=config)

        fake_response = SimpleOutput(name="test")
        client._instructor_client.chat.completions.create.return_value = fake_response

        client.complete(prompt="hello", response_model=SimpleOutput)

        call_kwargs = client._instructor_client.chat.completions.create.call_args.kwargs
        assert "extra_body" in call_kwargs
        assert call_kwargs["extra_body"] == {"seed": 42}

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_omits_seed_when_none(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete() omits extra_body when LLMConfig.seed is None."""
        config = LLMConfig(model="gpt-4", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        fake_response = SimpleOutput(name="test")
        client._instructor_client.chat.completions.create.return_value = fake_response

        client.complete(prompt="hello", response_model=SimpleOutput)

        call_kwargs = client._instructor_client.chat.completions.create.call_args.kwargs
        assert "extra_body" not in call_kwargs

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_passes_temperature(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete() passes temperature=0.7 as a top-level kwarg."""
        config = LLMConfig(model="gpt-4", api_key="sk-test", temperature=0.7)
        client = InstructorLLMClient(config=config)

        fake_response = SimpleOutput(name="test")
        client._instructor_client.chat.completions.create.return_value = fake_response

        client.complete(prompt="hello", response_model=SimpleOutput)

        call_kwargs = client._instructor_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_raw_passes_seed_in_extra_body(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete_raw() passes seed=42 via extra_body when LLMConfig.seed is set."""
        config = LLMConfig(model="gpt-4", api_key="sk-test", seed=42)
        client = InstructorLLMClient(config=config)

        mock_message = MagicMock()
        mock_message.content = "raw response"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        client._raw_client.chat.completions.create.return_value = mock_response

        client.complete_raw(prompt="hello")

        call_kwargs = client._raw_client.chat.completions.create.call_args.kwargs
        assert "extra_body" in call_kwargs
        assert call_kwargs["extra_body"] == {"seed": 42}

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_raw_omits_seed_when_none(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete_raw() omits extra_body when LLMConfig.seed is None."""
        config = LLMConfig(model="gpt-4", api_key="sk-test")
        client = InstructorLLMClient(config=config)

        mock_message = MagicMock()
        mock_message.content = "raw response"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        client._raw_client.chat.completions.create.return_value = mock_response

        client.complete_raw(prompt="hello")

        call_kwargs = client._raw_client.chat.completions.create.call_args.kwargs
        assert "extra_body" not in call_kwargs

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_complete_raw_passes_temperature(
        self, mock_instructor: MagicMock, mock_openai: MagicMock
    ) -> None:
        """complete_raw() passes temperature=0.7 as a named parameter."""
        config = LLMConfig(model="gpt-4", api_key="sk-test", temperature=0.7)
        client = InstructorLLMClient(config=config)

        mock_message = MagicMock()
        mock_message.content = "raw response"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        client._raw_client.chat.completions.create.return_value = mock_response

        client.complete_raw(prompt="hello")

        call_kwargs = client._raw_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7


# ---------------------------------------------------------------------------
# Cache key diversity tests
# ---------------------------------------------------------------------------


class TestCacheKeyDiversity:
    """Tests for cache key including temperature and seed."""

    def test_cache_key_includes_temperature_and_seed(self, tmp_path: Path) -> None:
        """Cache keys differ when temperature or seed differ."""
        cm = CacheManager(cache_dir=tmp_path)
        base = cm._make_key("prompt", "model", "Response", 0.0, None)
        diff_temp = cm._make_key("prompt", "model", "Response", 0.5, None)
        diff_seed = cm._make_key("prompt", "model", "Response", 0.0, 42)
        diff_both = cm._make_key("prompt", "model", "Response", 0.5, 42)
        assert len({base, diff_temp, diff_seed, diff_both}) == 4


# ---------------------------------------------------------------------------
# CachedLLMClient config inheritance tests
# ---------------------------------------------------------------------------


class TestCachedClientConfigInheritance:
    """Tests for CachedLLMClient extracting config from inner client."""

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_cached_client_inherits_config_from_inner(
        self, mock_instructor: MagicMock, mock_openai: MagicMock, tmp_path: Path
    ) -> None:
        """CachedLLMClient peeks inner._config for temperature and seed."""
        config = LLMConfig(model="gpt-4", api_key="sk-test", temperature=0.7, seed=123)
        inner = InstructorLLMClient(config=config)
        cm = CacheManager(cache_dir=tmp_path)
        cached = CachedLLMClient(inner, cm)

        assert cached._temperature == 0.7
        assert cached._seed == 123

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_cached_client_extracts_config_through_retry_layer(
        self, mock_instructor: MagicMock, mock_openai: MagicMock, tmp_path: Path
    ) -> None:
        """CachedLLMClient walks through RetryableLLMClient to find real LLMConfig."""
        config = LLMConfig(model="gpt-4", api_key="sk-test", temperature=0.7, seed=123)
        inner = InstructorLLMClient(config=config)
        retry = RetryableLLMClient(inner, RetryConfig(max_retries=2))
        cm = CacheManager(cache_dir=tmp_path)
        cached = CachedLLMClient(retry, cm)

        assert cached._temperature == 0.7
        assert cached._seed == 123

    @patch("metadata_enricher.llm.instructor_client.OpenAI")
    @patch("metadata_enricher.llm.instructor_client.instructor")
    def test_chain_too_deep_raises_runtime_error(
        self, mock_instructor: MagicMock, mock_openai: MagicMock, tmp_path: Path
    ) -> None:
        """CachedLLMClient raises RuntimeError when middleware chain exceeds 5 layers."""
        config = LLMConfig(model="gpt-4", api_key="sk-test", temperature=0.7, seed=123)
        leaf = InstructorLLMClient(config=config)
        candidate: LLMClient = leaf
        for _ in range(6):
            wrapper: LLMClient = RetryableLLMClient(candidate, RetryConfig(max_retries=1))
            candidate = wrapper
        cm = CacheManager(cache_dir=tmp_path)

        with pytest.raises(RuntimeError, match="exceeds 5 layers"):
            CachedLLMClient(candidate, cm)
