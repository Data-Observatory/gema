"""Factory for creating configured LLM clients from provider configs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    extra_body: dict[str, Any] | None = None,
    api_key: str | None = None,
) -> LLMClient:
    """Create a fully configured LLM client from a provider config.

    Wraps InstructorLLMClient with retry middleware and disk cache.
    Client instances are cached by a composite key of provider + model +
    temperature + seed + max_tokens + use_cache + use_retry + extra_body —
    calling with identical parameters returns the same client instance.

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
        extra_body: Raw OpenAI-compatible request body overrides, merged in
            alongside seed (e.g. {"thinking": {"type": "disabled"}} to work
            around DeepSeek V4's thinking mode rejecting forced tool_choice).
        api_key: Explicit key value, bypassing provider.api_key_env/os.environ
            entirely when given (visor's per-session key injection — see
            visor/glue.py — needs this: os.environ is one process-wide value,
            unusable when two hosted sessions hold different keys for the
            same provider). Omitted (the default) preserves the original
            env-var-only behavior byte-for-byte, cache key included.

    Returns:
        Configured LLMClient (wrapped with cache + retry).

    Raises:
        ValueError: If api_key is omitted and the provider's API key
            environment variable is not set.
    """
    extra_body_key = json.dumps(extra_body, sort_keys=True) if extra_body else None
    cache_key = (
        f"{provider.name}|{model}|t={temperature}|seed={seed}|mt={max_tokens}"
        f"|c={use_cache}|r={use_retry}|eb={extra_body_key}"
    )
    if api_key is not None:
        # Only appended for the explicit-key path -- keeps the env-var
        # path's cache key byte-identical to before. Without this,
        # two sessions passing *different* explicit keys for the same
        # provider/model would collide on one cached client and silently
        # share whichever key built it first (the same class of bug
        # reset_client_cache() exists to guard against for the env-var
        # path — see visor/app.py's _after_settings_saved).
        key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        cache_key += f"|k={key_fingerprint}"
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    resolved_api_key = api_key if api_key is not None else _resolve_api_key(provider.api_key_env)

    resolved_seed = seed if seed is not None else provider.seed

    config = LLMConfig(
        model=model,
        api_key=SecretStr(resolved_api_key),
        base_url=provider.base_url,
        temperature=temperature,
        seed=resolved_seed,
        max_tokens=max_tokens,
        extra_body=extra_body,
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


def clear_response_cache() -> None:
    """Purge every cached LLM response from the shared on-disk cache.

    Distinct from reset_client_cache(): that only drops in-memory client
    instances (so a changed API key takes effect) and never touches the
    on-disk diskcache.Cache at ~/.cache/gema -- dropping the
    CacheManager reference doesn't delete its backing files, since a new
    one just reopens the same directory. This actually empties it, so
    re-running the same resource calls the LLM again instead of replaying
    a prior cached response.
    """
    _get_shared_cache_manager().clear()
