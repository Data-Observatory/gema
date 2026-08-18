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

Residual limitation worth knowing about: apply_to_environ() still injects
a key into the one process-wide os.environ (create_llm_client() has no
other seam to read a key from -- see llm/factory.py). run_page.py refreshes
os.environ from this session's own settings immediately before each run to
keep the window tight, but two hosted sessions submitting a run for the
same provider at the exact same instant with different keys can still
race on that shared process state. Removing that race entirely would mean
threading an explicit resolved key through Pipeline/LLMClient construction
instead of env vars -- a real follow-up, out of scope here.
"""

from __future__ import annotations

import os

from nicegui import app

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
