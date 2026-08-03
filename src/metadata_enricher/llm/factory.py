"""Factory for creating configured LLM clients from provider configs."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import SecretStr

if TYPE_CHECKING:
    from datetime import timedelta

from metadata_enricher.cache import CachedLLMClient, CacheManager
from metadata_enricher.config.models import ProviderConfig
from metadata_enricher.llm.base import LLMClient, LLMConfig
from metadata_enricher.llm.instructor_client import InstructorLLMClient
from metadata_enricher.llm.retry import RetryableLLMClient

logger = logging.getLogger(__name__)

# Module-level cache of clients by composite key (provider + model + params)
_client_cache: dict[str, LLMClient] = {}
# Shared cache manager (created lazily)
_shared_cache_manager: CacheManager | None = None


def _get_shared_cache_manager() -> CacheManager:
    global _shared_cache_manager
    if _shared_cache_manager is None:
        _shared_cache_manager = CacheManager()
    return _shared_cache_manager


def _resolve_api_key(api_key_env: str) -> str:
    """Resolve API key from environment variable."""
    key = os.environ.get(api_key_env, "")
    if not key:
        msg = f"Environment variable '{api_key_env}' is not set or empty"
        raise ValueError(msg)
    return key


def create_llm_client(
    provider: ProviderConfig,
    model: str,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    seed: int | None = None,
    max_retries: int = 3,
    use_cache: bool = True,
    use_retry: bool = True,
    cache_dir: Path | None = None,
    cache_ttl: timedelta | None = None,
) -> LLMClient:
    """Create a fully configured LLM client from a provider config.

    Wraps InstructorLLMClient with retry middleware and disk cache.
    Client instances are cached by a composite key of provider + model +
    temperature + seed + max_tokens + use_cache + use_retry — calling
    with identical parameters returns the same client instance.

    Args:
        provider: ProviderConfig with base_url and api_key_env.
        model: Model name (e.g. "gpt-4", "glm-5-turbo").
        temperature: Sampling temperature.
        max_tokens: Max tokens for response.
        max_retries: Max retries for transport errors.
        use_cache: Enable disk cache wrapper.
        use_retry: Enable retry middleware.
        cache_dir: Override cache directory.
        cache_ttl: Override the cache entry TTL. Only applies when *cache_dir* is
            also given (isolated cache, e.g. golden-fixture recording) — the
            shared default cache always uses CacheManager's own default TTL.

    Returns:
        Configured LLMClient (wrapped with cache + retry).

    Raises:
        ValueError: If the API key environment variable is not set.
    """
    cache_key = f"{provider.name}|{model}|t={temperature}|seed={seed}|mt={max_tokens}|c={use_cache}|r={use_retry}"
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    api_key = _resolve_api_key(provider.api_key_env)

    resolved_seed = seed if seed is not None else provider.seed

    config = LLMConfig(
        model=model,
        api_key=SecretStr(api_key),
        base_url=provider.base_url,
        temperature=temperature,
        seed=resolved_seed,
        max_tokens=max_tokens,
    )

    client: LLMClient = InstructorLLMClient(config=config, max_retries=max_retries)

    if use_retry:
        client = RetryableLLMClient(client)

    if use_cache:
        if cache_dir:
            cm = (
                CacheManager(cache_dir=cache_dir, default_ttl=cache_ttl)
                if cache_ttl is not None
                else CacheManager(cache_dir=cache_dir)
            )
        else:
            cm = _get_shared_cache_manager()
        client = CachedLLMClient(client, cm)

    _client_cache[cache_key] = client
    logger.debug(
        "Created LLM client for provider '%s' (model=%s, key=%s)", provider.name, model, cache_key
    )
    return client


def reset_client_cache() -> None:
    """Clear the client cache. Useful for testing."""
    global _shared_cache_manager
    _client_cache.clear()
    _shared_cache_manager = None
