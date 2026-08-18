"""Run tab — form / paste-JSON / upload, one resource at a time.

One tab, three phases, all in the same panel (never a separate "Result"
tab): form -> running (live log + spinner) -> result. A disabled second
tab is confusing for a non-technical user, and this keeps the causal link
between "I pressed Run" and "the answer appeared" visible in one place.

Batch/folder upload is an explicit fast-follow (see the plan doc), not MVP —
the single-resource contract here generalizes later without changing
anything underneath.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from nicegui import events, run, ui

from metadata_enricher.config.models import DataverseExportConfig, PipelineConfig
from metadata_enricher.exporters.dataverse import to_dataverse_json
from metadata_enricher.llm.factory import clear_response_cache
from metadata_enricher.output import OutputWriter
from metadata_enricher.pipeline import PipelineResult
from metadata_enricher.schemas.base import Schema
from visor.glue import run_single, write_temp_input_from_dict, write_temp_input_from_text
from visor.i18n import t
from visor.log_stream import LogCapture, drain, start_capturing, stop_capturing
from visor.settings import VisorSettings, missing_required


def _format_duration(seconds: float) -> str:
    """Renders as "1m 23s" above a minute, "45s" below it -- avoids a
    "0m 45s" clutter for the overwhelmingly common single-resource run."""
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


FORM_FIELDS = (
    "url",
    "title",
    "description",
    "doi",
    "publisher",
    "frequency",
    "fetched_content",
    "context_hints",
)

# Renders as a multi-line ui.textarea instead of a single-line ui.input --
# free-text prose, same as fetched_content's own content, not a short value.
FORM_TEXTAREA_FIELDS = {"context_hints"}

# Example values shown as grayed placeholder text (never a prefilled
# value the user has to remember to clear before submitting). Left
# untranslated on purpose -- illustrative filler, not instructional copy;
# see run.json_template.* in visor/i18n.py for the one place example text
# actually explains something (the Paste JSON template).
FORM_FIELD_PLACEHOLDERS = {
    "url": "https://example.org/dataset/rainfall-2024",
    "title": "Annual Rainfall Measurements 2024",
    "description": "Monthly rainfall totals by station, national weather service.",
    "doi": "10.5880/GFZ.2.4.2021.001",
    "publisher": "Servicio Meteorológico Nacional",
    "frequency": "Monthly",
    "context_hints": (
        "Published in 2024. Contains 3 data files (CSV, XLSX, PDF). "
        "4 authors listed in the source repository, not mentioned on the page."
    ),
}


def _json_template() -> str:
    return json.dumps(
        {
            "url": "https://example.org/dataset",
            "title": t("run.json_template.title"),
            "description": t("run.json_template.description"),
            "doi": t("run.json_template.doi"),
            "publisher": t("run.json_template.publisher"),
            "frequency": t("run.json_template.frequency"),
            "fetched_content": t("run.json_template.fetched_content"),
            "context_hints": t("run.json_template.context_hints"),
        },
        indent=2,
        ensure_ascii=False,
    )


@dataclass
class _RunViewState:
    phase: str = "form"  # "form" | "running" | "result"
    result: PipelineResult | None = None
    error: str | None = None
    log_lines: list[str] = field(default_factory=list)
    capture: LogCapture | None = None
    submitted_text: str = ""
    start_time: float | None = None  # time.monotonic(), not wall-clock
    elapsed_seconds: float | None = None


def render_run_form(
    container: ui.element,
    pipeline_config: PipelineConfig,
    schema: Schema,
    current_settings: Callable[[], VisorSettings],
    on_go_to_settings: Callable[[], None],
    dataverse_export_config: DataverseExportConfig | None = None,
) -> Callable[[], object]:
    """Renders the Run tab and returns a zero-arg refresh function — call it
    after Settings are saved so a just-unblocked Run tab updates without
    needing a tab switch (tab_panels keep this tab mounted even while
    another tab is active, so it won't re-render on its own)."""
    container.clear()
    state = _RunViewState()

    @ui.refreshable
    def body() -> None:
        missing = missing_required(pipeline_config, current_settings())
        if missing and state.phase == "form":
            _render_settings_gate(missing, on_go_to_settings)
            return

        if state.phase == "form":
            _render_form_phase(pipeline_config, state, body.refresh)
        elif state.phase == "running":
            _render_running_phase(state)
        else:
            _render_result_phase(schema, state, body.refresh, pipeline_config, dataverse_export_config)

    with container:
        body()

    return body.refresh


def _render_settings_gate(missing: list[str], on_go_to_settings: Callable[[], None]) -> None:
    with ui.card().classes("w-full bg-warning").mark("run-settings-gate"):
        ui.label(t("run.gate.title")).classes("text-h6")
        ui.label(t("run.gate.missing", fields=", ".join(missing))).classes("text-caption")
        ui.button(t("run.gate.button"), on_click=on_go_to_settings).classes("q-mt-sm")


# Internal, language-independent values for the mode radio -- only the
# displayed label is translated (see the dict-options form below); the
# comparisons in _run() below key off these, never off display text.
_MODE_FORM = "form"
_MODE_PASTE = "paste"
_MODE_UPLOAD = "upload"


def _render_form_phase(
    pipeline_config: PipelineConfig, state: _RunViewState, refresh: Callable[[], object]
) -> None:
    ui.label(t("run.title")).classes("text-h5")

    mode = ui.radio(
        {
            _MODE_FORM: t("run.mode.form"),
            _MODE_PASTE: t("run.mode.paste"),
            _MODE_UPLOAD: t("run.mode.upload"),
        },
        value=_MODE_FORM,
    ).props("inline")

    form_box = ui.column().classes("w-full")
    with form_box:
        inputs: dict[str, ui.input | ui.textarea] = {}
        for name in FORM_FIELDS:
            label = t(f"run.field.{name}")
            placeholder = FORM_FIELD_PLACEHOLDERS.get(name)
            widget: ui.input | ui.textarea
            if name in FORM_TEXTAREA_FIELDS:
                widget = ui.textarea(label, placeholder=placeholder).props("rows=3")
            else:
                widget = ui.input(label, placeholder=placeholder)
            inputs[name] = widget.classes("w-full").mark(f"run-input-{name}")
            if name == "fetched_content":
                ui.label(t("run.field.fetched_content.hint")).classes("text-caption q-mb-sm")
            elif name == "context_hints":
                ui.label(t("run.field.context_hints.hint")).classes("text-caption q-mb-sm")
    form_box.bind_visibility_from(mode, "value", value=_MODE_FORM)

    paste_box = ui.column().classes("w-full")
    with paste_box:
        with ui.expansion(t("run.paste.help"), icon="help_outline"):
            ui.code(_json_template(), language="json").classes("w-full")
        paste_area = (
            ui.textarea(
                label=t("run.paste.label"),
                placeholder='{"url": "...", "title": "...", "description": "..."}',
            )
            .classes("w-full")
            .props("rows=14")
            .mark("run-paste-json")
        )
    paste_box.bind_visibility_from(mode, "value", value=_MODE_PASTE)

    upload_box = ui.column().classes("w-full")
    uploaded_text: list[str] = []
    with upload_box:

        async def _handle_upload(e: events.UploadEventArguments) -> None:
            uploaded_text.clear()
            uploaded_text.append(await e.file.text())
            ui.notify(t("run.upload.loaded", filename=e.file.name), type="positive")

        ui.upload(
            on_upload=_handle_upload,
            auto_upload=True,
            label=t("run.upload.label"),
        ).classes("w-full")
    upload_box.bind_visibility_from(mode, "value", value=_MODE_UPLOAD)

    status = ui.label("").classes("text-negative")

    async def _run() -> None:
        status.text = ""
        try:
            if mode.value == _MODE_FORM:
                data = {name: inp.value for name, inp in inputs.items() if inp.value}
                if not any(data.get(k) for k in ("url", "title", "description")):
                    status.text = t("run.error.fill_one")
                    return
                submitted_text = json.dumps(data, indent=2, ensure_ascii=False)
                input_path = write_temp_input_from_dict(data)
            elif mode.value == _MODE_PASTE:
                if not paste_area.value.strip():
                    status.text = t("run.error.paste_empty")
                    return
                submitted_text = paste_area.value
                input_path = write_temp_input_from_text(paste_area.value)
            else:
                if not uploaded_text:
                    status.text = t("run.error.upload_first")
                    return
                submitted_text = uploaded_text[0]
                input_path = write_temp_input_from_text(uploaded_text[0])
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not hidden
            status.text = t("run.error.read_input", error=exc)
            return

        state.phase = "running"
        state.log_lines = []
        state.submitted_text = submitted_text
        state.capture = start_capturing()
        state.start_time = time.monotonic()
        state.elapsed_seconds = None
        refresh()
        await _execute(pipeline_config, input_path, state, refresh)

    def _clear_cache() -> None:
        clear_response_cache()
        ui.notify(t("run.clear_cache.done"), type="positive")

    with ui.row().classes("items-center q-mt-md"):
        ui.button(t("run.button.run"), on_click=_run).mark("run-submit")
        ui.button(t("run.button.clear_cache"), on_click=_clear_cache).props("outline").mark(
            "run-clear-cache"
        )
        ui.label(t("run.clear_cache.hint")).classes("text-caption")


_AUTH_ERROR_MARKERS = (
    "401",
    "unauthorized",
    "invalid api key",
    "incorrect api key",
    "no auth credentials",
    "authenticationerror",
)


def _friendly_error(raw: str) -> str:
    """Rewrite a raw provider/transport error into something a non-programmer
    can act on. Providers report an invalid/revoked key as a bare HTTP 401
    with wording that varies (OpenRouter's "No auth credentials found" reads
    nothing like an API-key problem), so pattern-match the common shells
    instead of showing that text verbatim. The original string still reaches
    the user via the "Show details" log expansion below — this only changes
    the headline."""
    lowered = raw.lower()
    if any(marker in lowered for marker in _AUTH_ERROR_MARKERS):
        return t("run.result.auth_error", raw=raw)
    return raw


async def _execute(
    pipeline_config: PipelineConfig, input_path: Path, state: _RunViewState, refresh: Callable[[], object]
) -> None:
    assert state.capture is not None
    try:
        # Pipeline.run() is a blocking synchronous call — without offloading
        # it off the event loop, NiceGUI's websocket heartbeat freezes and
        # the app looks hung regardless of actual pipeline speed. The
        # running-phase's ui.timer drains state.capture.queue live, in
        # parallel, while this await is in flight.
        result = await run.io_bound(
            run_single, pipeline_config, input_path, run_id=state.capture.run_id
        )
    except Exception as exc:  # noqa: BLE001
        state.error = _friendly_error(str(exc))
        state.result = None
    else:
        state.result = result
        # PipelineResult.success wraps a resource-level failure (e.g. every
        # agent's provider call rejected an invalid key) without raising --
        # result.error carries the real reason, but the render side only
        # ever reads state.error, which the `except` branch above never
        # touched on this path. Without this, a failed-but-not-raised run
        # showed a bare "Unknown error" no matter what actually went wrong.
        # (result is run.io_bound()'s declared return type, never actually
        # None here — see _download_dataverse's identical guard below.)
        state.error = _friendly_error(result.error) if result and result.error else None
    finally:
        state.log_lines.extend(drain(state.capture.queue))
        stop_capturing(state.capture)
        state.capture = None
        input_path.unlink(missing_ok=True)
        state.elapsed_seconds = (
            time.monotonic() - state.start_time if state.start_time is not None else None
        )
        state.phase = "result"
        refresh()


def _render_submitted_input(submitted_text: str) -> None:
    if not submitted_text:
        return
    with ui.expansion(t("run.submitted_input"), icon="description").classes("w-full q-mb-sm").mark(
        "run-submitted-input"
    ):
        ui.code(submitted_text, language="json").classes("w-full")


def _render_token_usage(result: PipelineResult) -> None:
    usage = result.token_usage
    if usage.total_tokens == 0:
        return
    ui.label(
        t(
            "run.tokens_used",
            prompt=usage.prompt_tokens,
            completion=usage.completion_tokens,
            total=usage.total_tokens,
        )
    ).classes("text-caption").mark("result-token-usage")


def _render_models_used(result: PipelineResult) -> None:
    """The resolved model each agent actually ran with -- e.g. what an
    OpenRouter "~...-latest" alias really served, not just its configured
    name. Absent entirely (a mock client, or every call was a cache hit)
    means nothing to show, same convention as _render_token_usage."""
    if not result.models_used:
        return
    with ui.column().classes("gap-0").mark("result-models-used"):
        ui.label(t("run.models_used")).classes("text-caption")
        for agent_id, model in sorted(result.models_used.items()):
            ui.label(f"- {agent_id}: {model}").classes("text-caption")


def _render_running_phase(state: _RunViewState) -> None:
    ui.label(t("run.running.title")).classes("text-h5")
    _render_submitted_input(state.submitted_text)
    with ui.row().classes("items-center"):
        ui.spinner(size="lg")
        ui.label(t("run.running.hint"))
        elapsed_label = (
            ui.label(t("run.running.elapsed", duration=_format_duration(0)))
            .classes("text-caption")
            .mark("run-elapsed")
        )

    log_box = ui.log(max_lines=500).classes("w-full").style("height: 260px").mark("run-log")
    for line in state.log_lines:
        log_box.push(line)

    def _poll() -> None:
        if state.phase != "running" or state.capture is None:
            timer.active = False
            return
        if state.start_time is not None:
            elapsed_label.text = t(
                "run.running.elapsed",
                duration=_format_duration(time.monotonic() - state.start_time),
            )
        for line in drain(state.capture.queue):
            state.log_lines.append(line)
            log_box.push(line)

    timer = ui.timer(0.3, _poll)


def _render_result_phase(
    schema: Schema,
    state: _RunViewState,
    refresh: Callable[[], object],
    pipeline_config: PipelineConfig,
    dataverse_export_config: DataverseExportConfig | None,
) -> None:
    def _reset() -> None:
        state.phase = "form"
        state.result = None
        state.error = None
        state.log_lines = []
        state.submitted_text = ""
        state.start_time = None
        state.elapsed_seconds = None
        refresh()

    with ui.row().classes("items-center q-mb-sm"):
        if state.result is not None and state.result.success:
            ui.button(
                t("run.result.download_json"), on_click=lambda: _download(schema, state)
            ).mark("result-download")
            if dataverse_export_config is not None:
                ui.button(
                    t("run.result.download_dataverse"),
                    on_click=lambda: _download_dataverse(state, pipeline_config, dataverse_export_config),
                ).props("outline").mark("result-download-dataverse")
        ui.button(t("run.result.run_another"), on_click=_reset).mark("result-back")

    if state.elapsed_seconds is not None:
        ui.label(
            t("run.result.completed_in", duration=_format_duration(state.elapsed_seconds))
        ).classes("text-caption").mark("result-elapsed")

    _render_submitted_input(state.submitted_text)
    if state.result is not None:
        _render_token_usage(state.result)
        _render_models_used(state.result)

    if state.result is not None and state.result.success:
        assert state.result.document is not None
        json_str = OutputWriter(schema).format_json(state.result.document)

        if state.result.warnings:
            with ui.card().classes("bg-warning w-full"):
                ui.label(t("run.result.warnings_title")).classes("text-bold")
                for warning in state.result.warnings:
                    ui.label(f"- {warning}")

        ui.label(t("run.result.title")).classes("text-h6").mark("result-success")
        with ui.scroll_area().classes("w-full border").style("height: 320px"):
            ui.code(json_str, language="json").classes("w-full").mark("result-json")
    else:
        ui.label(t("run.result.failure_title")).classes(
            "text-h6 text-negative"
        ).mark("result-failure")
        ui.label(state.error or t("run.result.unknown_error")).mark("result-error")

    if state.log_lines:
        with ui.expansion(
            t("run.result.show_details", count=len(state.log_lines)),
            value=state.result is None or not state.result.success,
        ).classes("w-full q-mt-md"):
            with ui.scroll_area().classes("w-full border").style("height: 200px"):
                for line in state.log_lines:
                    ui.label(line).classes("text-caption")


def _download(schema: Schema, state: _RunViewState) -> None:
    assert state.result is not None and state.result.document is not None
    json_str = OutputWriter(schema).format_json(state.result.document)
    # Explicit bytes, not str: NiceGUI's test-simulation Download.content()
    # doesn't do the str->bytes conversion the real implementation does —
    # caught by visor/tests/test_app_e2e.py's real click-through test.
    ui.download.content(
        json_str.encode("utf-8"), filename="metadata.json", media_type="application/json"
    )


async def _download_dataverse(
    state: _RunViewState,
    pipeline_config: PipelineConfig,
    dataverse_export_config: DataverseExportConfig,
) -> None:
    assert state.result is not None and state.result.document is not None

    provider = None
    if dataverse_export_config.enabled:
        provider = next(
            (p for p in pipeline_config.providers if p.name == dataverse_export_config.agent.provider), None
        )
        if provider is None:
            ui.notify(
                t(
                    "run.dataverse.provider_missing",
                    provider=dataverse_export_config.agent.provider,
                ),
                type="warning",
            )

    try:
        # to_dataverse_json() can make a real (blocking) LLM call when
        # classification is enabled — offload it the same way the main
        # pipeline run is offloaded, or the UI freezes for its duration.
        export_result = await run.io_bound(
            to_dataverse_json, state.result.document, dataverse_export_config, provider
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not hidden
        ui.notify(t("run.dataverse.build_failed", error=exc), type="negative")
        return

    if export_result is None:  # run.io_bound()'s declared return type, never actually None here
        ui.notify(t("run.dataverse.no_result"), type="negative")
        return

    for warning in export_result.warnings:
        ui.notify(warning, type="warning")

    json_str = json.dumps(export_result.dataset_json, ensure_ascii=False, indent=2)
    ui.download.content(
        json_str.encode("utf-8"), filename="dataverse_dataset.json", media_type="application/json"
    )
