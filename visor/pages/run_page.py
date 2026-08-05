"""Run screen — form / paste-JSON / upload, one resource at a time.

Batch/folder upload is an explicit fast-follow (see the plan doc), not MVP —
the single-resource contract here generalizes later without changing
anything underneath.
"""

from __future__ import annotations

from typing import Callable

from nicegui import events, run, ui

from metadata_enricher.config.models import PipelineConfig
from metadata_enricher.pipeline import PipelineResult
from visor.glue import run_single, write_temp_input_from_dict, write_temp_input_from_text

FORM_FIELDS = ("url", "title", "description", "publisher", "frequency", "fetched_content")


def render_run_form(
    container: ui.element,
    pipeline_config: PipelineConfig,
    on_result: Callable[[PipelineResult], None],
    on_error: Callable[[str], None],
) -> None:
    container.clear()
    with container:
        ui.label("Run a resource").classes("text-h5")

        mode = ui.radio(["Fill a form", "Paste JSON", "Upload a file"], value="Fill a form").props(
            "inline"
        )

        form_box = ui.column().classes("w-full")
        with form_box:
            inputs = {
                name: ui.input(name.replace("_", " ").title())
                .classes("w-full")
                .mark(f"run-input-{name}")
                for name in FORM_FIELDS
            }
        form_box.bind_visibility_from(mode, "value", value="Fill a form")

        paste_box = ui.column().classes("w-full")
        with paste_box:
            paste_area = (
                ui.textarea(
                    label="Paste raw JSON",
                    placeholder='{"url": "...", "title": "...", "description": "..."}',
                )
                .classes("w-full")
                .props("rows=14")
            )
        paste_box.bind_visibility_from(mode, "value", value="Paste JSON")

        upload_box = ui.column().classes("w-full")
        uploaded_text: list[str] = []
        with upload_box:

            async def _handle_upload(e: events.UploadEventArguments) -> None:
                uploaded_text.clear()
                uploaded_text.append(await e.file.text())
                ui.notify(f"Loaded {e.file.name}", type="positive")

            ui.upload(
                on_upload=_handle_upload,
                auto_upload=True,
                label="Upload a .json input file",
            ).classes("w-full")
        upload_box.bind_visibility_from(mode, "value", value="Upload a file")

        status = ui.label("").classes("text-negative")
        spinner = ui.spinner(size="lg")
        spinner.set_visibility(False)

        async def _run() -> None:
            status.text = ""
            try:
                if mode.value == "Fill a form":
                    data = {name: field.value for name, field in inputs.items() if field.value}
                    if not any(data.get(k) for k in ("url", "title", "description")):
                        status.text = "Fill at least url, title, or description."
                        return
                    input_path = write_temp_input_from_dict(data)
                elif mode.value == "Paste JSON":
                    if not paste_area.value.strip():
                        status.text = "Paste some JSON first."
                        return
                    input_path = write_temp_input_from_text(paste_area.value)
                else:
                    if not uploaded_text:
                        status.text = "Upload a file first."
                        return
                    input_path = write_temp_input_from_text(uploaded_text[0])
            except Exception as exc:  # noqa: BLE001 - surfaced to the user, not hidden
                status.text = f"Could not read input: {exc}"
                return

            run_button.disable()
            spinner.set_visibility(True)
            try:
                # Pipeline.run() is a blocking synchronous call — without
                # offloading it off the event loop, NiceGUI's websocket
                # heartbeat freezes and the app looks hung regardless of
                # actual pipeline speed.
                result = await run.io_bound(run_single, pipeline_config, input_path)
            except Exception as exc:  # noqa: BLE001
                on_error(str(exc))
            else:
                if result is not None:
                    on_result(result)
            finally:
                input_path.unlink(missing_ok=True)
                # on_result()/on_error() already cleared this container (and
                # everything in it, including this button) to show the next
                # screen — touching a deleted element only logs a harmless
                # warning, but skipping it is cheap and exactly correct.
                if not run_button.is_deleted:
                    run_button.enable()
                    spinner.set_visibility(False)

        run_button = ui.button("Run", on_click=_run).classes("q-mt-md").mark("run-submit")
