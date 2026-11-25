"""Test setup: make ``intake_app`` importable; nothing here talks to a real LLM or Dataverse.

Run from the repo root (gema's own ``src/`` is on pytest's pythonpath):

    uv run --with fastapi --with python-multipart --with jinja2 \
        pytest dataverse-demo/intake/tests
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from intake_app.store import Store  # noqa: E402


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "intake.db")
    s.init()
    return s
