"""Tests for visor.model_catalog — real per-provider model-list fetching."""

from __future__ import annotations

import httpx
import pytest

from metadata_enricher.config.models import ProviderConfig
from visor.model_catalog import fetch_provider_models


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=httpx.Request("GET", "http://x"), response=self)  # type: ignore[arg-type]


class TestFetchProviderModels:
    def test_returns_sorted_ids_from_data_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def fake_get(url: str, headers: dict, timeout: float) -> _FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResponse({"data": [{"id": "gpt-4o"}, {"id": "gpt-3.5"}]})

        monkeypatch.setattr(httpx, "get", fake_get)
        provider = ProviderConfig(name="openai", base_url="https://api.openai.com/v1", api_key_env="OPENAI_API_KEY")

        result = fetch_provider_models(provider, "sk-test")

        assert result == ["gpt-3.5", "gpt-4o"]
        assert captured["url"] == "https://api.openai.com/v1/models"
        assert captured["headers"] == {"Authorization": "Bearer sk-test"}

    def test_defaults_base_url_when_provider_has_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def fake_get(url: str, headers: dict, timeout: float) -> _FakeResponse:
            captured["url"] = url
            return _FakeResponse({"data": []})

        monkeypatch.setattr(httpx, "get", fake_get)
        provider = ProviderConfig(name="anthropic", base_url=None, api_key_env="ANTHROPIC_API_KEY")

        fetch_provider_models(provider, "sk-test")

        assert captured["url"] == "https://api.openai.com/v1/models"

    def test_no_auth_header_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}

        def fake_get(url: str, headers: dict, timeout: float) -> _FakeResponse:
            captured["headers"] = headers
            return _FakeResponse({"data": []})

        monkeypatch.setattr(httpx, "get", fake_get)
        provider = ProviderConfig(name="openrouter", base_url="https://openrouter.ai/api/v1", api_key_env="X")

        fetch_provider_models(provider, None)

        assert captured["headers"] == {}

    def test_raises_on_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_get(url: str, headers: dict, timeout: float) -> _FakeResponse:
            return _FakeResponse({}, status_code=401)

        monkeypatch.setattr(httpx, "get", fake_get)
        provider = ProviderConfig(name="openai", base_url=None, api_key_env="OPENAI_API_KEY")

        with pytest.raises(httpx.HTTPStatusError):
            fetch_provider_models(provider, "bad-key")

    def test_ignores_malformed_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_get(url: str, headers: dict, timeout: float) -> _FakeResponse:
            return _FakeResponse({"data": [{"id": "gpt-4o"}, "not-a-dict", {"no_id": True}]})

        monkeypatch.setattr(httpx, "get", fake_get)
        provider = ProviderConfig(name="openai", base_url=None, api_key_env="OPENAI_API_KEY")

        assert fetch_provider_models(provider, "sk-test") == ["gpt-4o"]
