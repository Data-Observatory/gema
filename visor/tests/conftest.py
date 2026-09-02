"""Test fixtures for visor."""

import sys
from pathlib import Path

import pytest

# Allow `import visor` — visor/ is an application, not an installed package.
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)


@pytest.fixture(autouse=True)
def _default_visor_language_english(monkeypatch):
    """Every existing click-through test was written against visor's
    original (English) copy. visor's real default is Spanish (see
    visor/i18n.py's DEFAULT_LANGUAGE) -- pin it to English here so those
    tests keep asserting what they say, without having to touch every one
    of them. The i18n feature's own tests override this back to Spanish
    (or switch languages explicitly via the picker) where they need to."""
    monkeypatch.setattr("visor.i18n.DEFAULT_LANGUAGE", "en")


@pytest.fixture(autouse=True)
def _isolated_visor_settings_path(monkeypatch, tmp_path):
    """settings_path() resolves via platformdirs.user_config_dir(), which
    only honors the XDG_CONFIG_HOME env var on Linux/macOS -- on Windows
    it always reads %APPDATA%, regardless of XDG_CONFIG_HOME. Many
    existing tests monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path /
    "config")) for isolation, which works on the Linux/macOS CI runners
    but silently no-ops on windows-latest: every test in that job's
    single pytest session then reads and writes the SAME real
    settings.json on the runner, and later tests observe earlier tests'
    leftover/overwritten values -- confirmed as the cause of an 8-test
    failure on windows-latest in visor-build.yml (all passing on
    ubuntu-latest and macos-latest) after the Agents-tab override
    persistence feature added enough cross-test settings.json writes to
    start colliding.

    Patching settings_path() itself -- the one seam load_settings() and
    save_settings() both fall back to -- isolates every test's
    native-mode settings file the same way on every OS, independent of
    platformdirs' per-OS env var quirks. Existing per-test
    XDG_CONFIG_HOME monkeypatches become redundant but harmless (and are
    left in place rather than churning every call site for this)."""
    monkeypatch.setattr("visor.settings.settings_path", lambda: tmp_path / "isolated-settings.json")
