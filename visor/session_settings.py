"""Per-browser-session VisorSettings storage for hosted mode.

Native mode (VISOR_NATIVE != "0", the default) keeps using visor.settings's
plain settings.json file directly -- there's only ever one local user in
that mode, and the file survives across launches with no "session" concept
needed. Deliberately kept in a separate module (rather than folded into
visor/settings.py) so that file stays pure stdlib and unit-testable without
booting a NiceGUI page -- see visor/log_stream.py's module docstring for
the same rationale applied to log capture.

Hosted mode (VISOR_NATIVE=0, potentially many people connecting to one
running process over Tailscale) must never let one guest's Settings edits
reach anyone else's session -- confirmed broken in practice: changing a
provider's key in one browser tab was visible in every other connected
session, because every session's Settings tab ultimately read from and
wrote to the one shared settings.json. Each hosted session now gets its
own private VisorSettings, backed by NiceGUI's app.storage.user (a
server-side-persisted, per-browser store keyed by a signed session cookie
-- see visor/settings.py's storage_secret()). A fresh guest session starts
EMPTY, never seeded from the operator's own file-based settings: doing
that would leak the operator's real API key value into every guest's
storage the moment they open the page.

Previously, run_page.py worked around the one process-wide os.environ
(create_llm_client()'s only key-resolution seam) by refreshing it from
this session's own settings immediately before each run -- narrowing,
but not closing, a race where two hosted sessions submitting a run for
the same provider at the exact same instant with different keys could
still collide on that shared process state. build_llm_factory() below
closes it properly: create_llm_client() now accepts an explicit api_key
that bypasses os.environ entirely, and AgentRegistry already calls
through an injectable llm_factory rather than create_llm_client
directly (see agents/registry.py) -- so visor never needs to touch
os.environ for provider keys at all.
"""

from __future__ import annotations

import os
from typing import Any

from nicegui import app

from metadata_enricher.config.models import ProviderConfig
from metadata_enricher.llm.base import LLMClient
from metadata_enricher.llm.factory import create_llm_client
from visor.settings import VisorSettings, load_settings, save_settings

_STORAGE_KEY = "visor_settings"


def _hosted() -> bool:
    return os.environ.get("VISOR_NATIVE", "1") == "0"


def load_session_settings() -> VisorSettings:
    """Must be called from inside a page render or event handler in hosted
    mode (app.storage.user requires that); native mode falls through to
    the plain file and has no such requirement."""
    if not _hosted():
        return load_settings()
    data = app.storage.user.get(_STORAGE_KEY)
    return VisorSettings.from_dict(data) if isinstance(data, dict) else VisorSettings()


def save_session_settings(settings: VisorSettings) -> None:
    if not _hosted():
        save_settings(settings)
        return
    app.storage.user[_STORAGE_KEY] = settings.to_dict()


def build_llm_factory(settings: VisorSettings) -> Any:
    """An LLMClientFactory (see agents/registry.py) closing over *settings*'
    own keys -- pass to visor.glue.run_single(llm_factory=...) so this
    session's run always uses its own key for a provider, never whatever
    the process-wide os.environ currently happens to hold. Falls back to
    create_llm_client's normal os.environ lookup when this session hasn't
    got a key for that particular provider (e.g. one it doesn't use),
    rather than failing outright.

    Return type is Any, not the LLMClientFactory Protocol, so this module
    doesn't have to import agents.registry (a heavier, orchestration-layer
    module) just for a type annotation -- the closure's call shape matches
    structurally, which is all a Protocol ever checks.
    """

    def factory(
        provider: ProviderConfig,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMClient:
        return create_llm_client(
            provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
            api_key=settings.env.get(provider.api_key_env) or None,
        )

    return factory
