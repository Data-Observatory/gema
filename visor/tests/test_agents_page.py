"""Tests for visor.pages.agents_page's upload handler.

Full click-through (rendering, per-agent cards, Advanced section content)
is covered in test_ui_navigation.py — this file is a focused unit test on
_handle_upload's PipelineConfig field round-trip, the same style already
used for visor.settings/visor.bootstrap (no app boot needed).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from metadata_enricher.config.models import PipelineConfig
from visor.pages.agents_page import _handle_upload

pytestmark = pytest.mark.asyncio


def _minimal_config_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_name": "datacite-4.6",
        "agents": [
            {
                "id": "a0",
                "name": "Agent 0",
                "fields": ["titles"],
                "prompt": "Do something.",
                "provider": "p0",
            }
        ],
        "providers": [{"name": "p0", "api_key_env": "P0_API_KEY"}],
    }
    base.update(overrides)
    return base


class _FakeFile:
    def __init__(self, text: str) -> None:
        self._text = text

    async def text(self) -> str:
        return self._text


class _FakeUploadEvent:
    def __init__(self, text: str) -> None:
        self.file = _FakeFile(text)


class TestHandleUpload:
    @pytest.fixture(autouse=True)
    def _stub_notify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # _handle_upload calls ui.notify() on both the success and failure
        # paths -- this module boots no NiceGUI client/slot context, which
        # ui.notify() requires. Stub it out; these tests assert on
        # pipeline_config's own state, never on what was displayed.
        monkeypatch.setattr("visor.pages.agents_page.ui.notify", lambda *a, **k: None)

    async def test_carries_enable_content_fetch_and_doi_resolution(self) -> None:
        """Regression: _handle_upload copies every other top-level
        PipelineConfig scalar (enable_identifier_enrichment, validate_pids,
        ...) from the uploaded/validated config back onto the live one, but
        used to miss these two -- an uploaded file with either flag set
        would silently revert to the default (False) the moment it was
        applied."""
        pipeline_config = PipelineConfig(**_minimal_config_dict())
        assert pipeline_config.enable_content_fetch is False
        assert pipeline_config.enable_doi_resolution is False

        uploaded = _minimal_config_dict(enable_content_fetch=True, enable_doi_resolution=True)
        event = _FakeUploadEvent(json.dumps(uploaded))
        refreshed: list[bool] = []

        await _handle_upload(event, pipeline_config, lambda: refreshed.append(True))

        assert pipeline_config.enable_content_fetch is True
        assert pipeline_config.enable_doi_resolution is True
        assert refreshed == [True]

    async def test_rejects_invalid_upload_without_mutating_config(self) -> None:
        pipeline_config = PipelineConfig(**_minimal_config_dict())
        event = _FakeUploadEvent("not json")
        refreshed: list[bool] = []

        await _handle_upload(event, pipeline_config, lambda: refreshed.append(True))

        assert pipeline_config.enable_content_fetch is False
        assert refreshed == []
