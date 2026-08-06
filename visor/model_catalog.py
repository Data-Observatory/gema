"""Live model-list fetching for the Agents tab's Model combobox.

Every provider in this project is treated as OpenAI-API-compatible (see
llm/factory.py — ProviderConfig has no per-provider auth-scheme field), so
this hits the standard ``GET {base_url}/models`` endpoint with Bearer
auth — the same assumption the rest of the app already makes, not a new
one introduced here.

Best-effort only: a provider that doesn't implement this endpoint, or has
no key configured yet, just means no live suggestions are offered — the
Model field's ``with_input=True`` combobox still accepts typing any model
id by hand, so a failed refresh never blocks the field from being used.
"""

from __future__ import annotations

import httpx

from metadata_enricher.config.models import ProviderConfig

DEFAULT_BASE_URL = "https://api.openai.com/v1"


def fetch_provider_models(
    provider: ProviderConfig, api_key: str | None, *, timeout: float = 10.0
) -> list[str]:
    """Model ids from *provider*'s own `/models` endpoint. Raises
    httpx.HTTPError on any network/HTTP failure — the caller decides how
    to surface that (e.g. a non-blocking notification)."""
    base_url = (provider.base_url or DEFAULT_BASE_URL).rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = httpx.get(f"{base_url}/models", headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    entries = payload.get("data", []) if isinstance(payload, dict) else []
    return sorted({str(entry["id"]) for entry in entries if isinstance(entry, dict) and "id" in entry})
