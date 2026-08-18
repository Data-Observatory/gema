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
