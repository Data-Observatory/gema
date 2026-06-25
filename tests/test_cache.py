"""Tests for CacheManager and CachedLLMClient."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel

from metadata_enricher.cache import CachedLLMClient, CacheManager


class SimpleOutput(BaseModel):
    name: str


class MockLLMClient:
    def __init__(self, model_name: str = "mock-model") -> None:
        self._model = model_name
        self.call_count = 0

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        prompt: str,
        response_model: type[BaseModel],
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> BaseModel:
        self.call_count += 1
        return response_model(name=prompt)

    def complete_raw(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        self.call_count += 1
        return f"raw:{prompt}"


# ---------------------------------------------------------------------------
# CacheManager tests
# ---------------------------------------------------------------------------


class TestCacheManager:
    """CacheManager unit tests."""

    def test_set_get_roundtrip(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        cm.set("k1", {"answer": 42})
        assert cm.get("k1") == {"answer": 42}

    def test_get_returns_none_on_miss(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        assert cm.get("nonexistent") is None

    def test_clear_removes_all_entries(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        cm.set("a", 1)
        cm.set("b", 2)
        cm.clear()
        assert cm.get("a") is None
        assert cm.get("b") is None

    def test_stats(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        assert cm.stats() == {"size": 0, "keys": 0}
        cm.set("x", {"v": 1})
        cm.set("y", {"v": 2})
        s = cm.stats()
        assert s["size"] == 2
        assert s["keys"] == 2

    def test_make_key_is_deterministic(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        k1 = cm._make_key("hello", "gpt-4", "MyModel", 0.0, None)
        k2 = cm._make_key("hello", "gpt-4", "MyModel", 0.0, None)
        assert k1 == k2
        assert isinstance(k1, str)
        assert len(k1) == 64

    def test_make_key_differs_on_any_input(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        k1 = cm._make_key("hello", "gpt-4", "MyModel", 0.0, None)
        k2 = cm._make_key("world", "gpt-4", "MyModel", 0.0, None)
        k3 = cm._make_key("hello", "gpt-3.5", "MyModel", 0.0, None)
        k4 = cm._make_key("hello", "gpt-4", "OtherModel", 0.0, None)
        assert len({k1, k2, k3, k4}) == 4

    def test_custom_ttl(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path, default_ttl=timedelta(seconds=1))
        cm.set("k", {"v": 1})
        assert cm.get("k") == {"v": 1}

    def test_cache_dir_created(self, tmp_path: Path) -> None:
        d = tmp_path / "sub" / "dir"
        cm = CacheManager(cache_dir=d)
        assert d.is_dir()
        cm.close()

    def test_close(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        cm.set("k", {"v": 1})
        cm.close()
        assert (tmp_path / ".diskcache").is_dir() or any(tmp_path.iterdir())


# ---------------------------------------------------------------------------
# CachedLLMClient tests
# ---------------------------------------------------------------------------


class TestCachedLLMClient:
    """CachedLLMClient unit tests."""

    def test_calls_inner_on_miss(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        inner = MockLLMClient()
        cached = CachedLLMClient(inner, cm)

        result = cached.complete("prompt-x", SimpleOutput)

        assert isinstance(result, SimpleOutput)
        assert result.name == "prompt-x"
        assert inner.call_count == 1

    def test_returns_cached_on_hit(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        inner = MockLLMClient()
        cached = CachedLLMClient(inner, cm)

        result1 = cached.complete("prompt-x", SimpleOutput)
        result2 = cached.complete("prompt-x", SimpleOutput)

        assert result2.name == result1.name
        assert inner.call_count == 1

    def test_cache_miss_on_different_prompt(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        inner = MockLLMClient()
        cached = CachedLLMClient(inner, cm)

        cached.complete("prompt-a", SimpleOutput)
        cached.complete("prompt-b", SimpleOutput)

        assert inner.call_count == 2

    def test_model_property(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        inner = MockLLMClient(model_name="my-custom-model")
        cached = CachedLLMClient(inner, cm)
        assert cached.model == "my-custom-model"

    def test_complete_raw_caches_and_returns(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        inner = MockLLMClient()
        cached = CachedLLMClient(inner, cm)

        result1 = cached.complete_raw("hello")
        result2 = cached.complete_raw("hello")

        assert result1 == "raw:hello"
        assert result2 == "raw:hello"
        assert inner.call_count == 1

    def test_complete_raw_miss_on_different_prompt(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        inner = MockLLMClient()
        cached = CachedLLMClient(inner, cm)

        cached.complete_raw("hello")
        cached.complete_raw("world")

        assert inner.call_count == 2

    def test_close_underlying_cache(self, tmp_path: Path) -> None:
        cm = CacheManager(cache_dir=tmp_path)
        inner = MockLLMClient()
        cached = CachedLLMClient(inner, cm)
        cached.complete("test", SimpleOutput)
        cm.close()
