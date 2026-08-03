"""Caching layer for LLM clients using diskcache."""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import diskcache
from pydantic import BaseModel

if TYPE_CHECKING:
    from metadata_enricher.llm.base import LLMClient

logger = logging.getLogger(__name__)


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
    ) -> str:
        raw = f"{prompt}:{model}:{response_model_name}:{temperature}:{seed}"
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

    def stats(self) -> dict[str, int]:
        return {
            "size": len(self._cache),
            "keys": len(list(self._cache.iterkeys())),
        }

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
            prompt, self.model, response_model.__name__, self._temperature, self._seed
        )
        cached = self._cache.get(key)
        if cached is not None:
            logger.debug("Cache HIT for key=%s", key[:12])
            return response_model.model_validate(cached)

        logger.debug("Cache MISS for key=%s", key[:12])
        result = self._inner.complete(prompt, response_model, system_prompt, **kwargs)
        self._cache.set(key, result.model_dump())
        return result

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
