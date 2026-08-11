"""Caching layer for LLM clients using diskcache."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import diskcache
from pydantic import BaseModel

if TYPE_CHECKING:
    from metadata_enricher.llm.base import LLMClient

from metadata_enricher.types import TokenUsage

logger = logging.getLogger(__name__)


def _cached_data(cached: dict[str, Any]) -> dict[str, Any]:
    """Cache entries written before token-usage tracking was added store the
    bare model dump directly; entries written since wrap it as
    {"data": ..., "usage": ...}. Accept both so already-committed golden
    fixture caches (tests/fixtures/golden/cache/cache.db) keep working
    without re-recording."""
    if "data" in cached and "usage" in cached:
        return cast("dict[str, Any]", cached["data"])
    return cached


class CacheManager:
    """Wraps diskcache.Cache for LLM response caching."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        default_ttl: timedelta = timedelta(days=7),
    ) -> None:
        self.default_ttl = default_ttl
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "metagen"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = diskcache.Cache(str(cache_dir))
        logger.debug("CacheManager initialised at %s", cache_dir)

    def _make_key(
        self,
        prompt: str,
        model: str,
        response_model_name: str,
        temperature: float,
        seed: int | None,
        extra_body: dict[str, Any] | None = None,
    ) -> str:
        raw = f"{prompt}:{model}:{response_model_name}:{temperature}:{seed}"
        # Appended only when set, so keys for the (overwhelmingly common) no-override
        # case stay identical to before extra_body existed — preserves committed
        # golden-fixture cache entries (tests/fixtures/golden/cache/cache.db).
        if extra_body:
            raw += f":{json.dumps(extra_body, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        return cast("dict[str, Any] | None", self._cache.get(key))

    def set(
        self,
        key: str,
        value: dict[str, Any],
        ttl: timedelta | None = None,
    ) -> None:
        expire = int((ttl or self.default_ttl).total_seconds())
        self._cache.set(key, value, expire=expire)

    def clear(self) -> None:
        self._cache.clear()

    def close(self) -> None:
        self._cache.close()


class CachedLLMClient:
    """LLMClient wrapper that adds transparent disk-backed caching."""

    def __init__(self, inner: LLMClient, cache_manager: CacheManager) -> None:
        self._inner = inner
        self._cache = cache_manager
        candidate: LLMClient = inner
        for _ in range(5):
            if not hasattr(candidate, "inner"):
                break
            candidate = candidate.inner
        else:
            msg = "Middleware chain exceeds 5 layers; cannot locate LLMConfig"
            raise RuntimeError(msg)
        config = getattr(candidate, "_config", None)
        if config is None:
            msg = (
                f"Could not locate LLMConfig in middleware chain "
                f"(leaf type: {type(candidate).__name__}). "
                f"Ensure the chain terminates with an InstructorLLMClient."
            )
            raise RuntimeError(msg)
        self._temperature: float = getattr(config, "temperature", 0.0)
        self._seed: int | None = getattr(config, "seed", None)
        self._extra_body: dict[str, Any] | None = getattr(config, "extra_body", None)

    @property
    def model(self) -> str:
        return self._inner.model

    def complete(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> BaseModel:
        key = self._cache._make_key(
            prompt, self.model, response_model.__name__, self._temperature, self._seed,
            self._extra_body,
        )
        cached = self._cache.get(key)
        if cached is not None:
            logger.debug("Cache HIT for key=%s", key[:12])
            return response_model.model_validate(_cached_data(cached))

        logger.debug("Cache MISS for key=%s", key[:12])
        result = self._inner.complete(prompt, response_model, system_prompt, **kwargs)
        self._cache.set(key, {"data": result.model_dump(), "usage": TokenUsage().model_dump()})
        return result

    def complete_with_usage(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> tuple[BaseModel, TokenUsage]:
        """Same cache key as complete() — a cache hit recorded by either
        method is visible to the other. A hit costs no new tokens (nothing
        was actually called), so usage is 0 regardless of what the original
        call recorded; only a real cache miss reports real usage."""
        key = self._cache._make_key(
            prompt, self.model, response_model.__name__, self._temperature, self._seed,
            self._extra_body,
        )
        cached = self._cache.get(key)
        if cached is not None:
            logger.debug("Cache HIT for key=%s", key[:12])
            return response_model.model_validate(_cached_data(cached)), TokenUsage()

        logger.debug("Cache MISS for key=%s", key[:12])
        inner_with_usage = getattr(self._inner, "complete_with_usage", None)
        if inner_with_usage is not None:
            result, usage = inner_with_usage(prompt, response_model, system_prompt, **kwargs)
        else:
            result = self._inner.complete(prompt, response_model, system_prompt, **kwargs)
            usage = TokenUsage()
        self._cache.set(key, {"data": result.model_dump(), "usage": usage.model_dump()})
        return result, usage

    def complete_raw(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        key = self._cache._make_key(prompt, self.model, "raw", self._temperature, self._seed)
        cached = self._cache.get(key)
        if cached is not None:
            logger.debug("Cache HIT for key=%s (raw)", key[:12])
            return cast(str, cached["raw"])

        logger.debug("Cache MISS for key=%s (raw)", key[:12])
        result = self._inner.complete_raw(prompt, system_prompt, **kwargs)
        self._cache.set(key, {"raw": result})
        return result
