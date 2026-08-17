"""Launcher entry point — a tiny native control-panel window (Start/Restart/
Stop) that spawns the hosted visor server as a **subprocess**, and the sole
PyInstaller entry point (see visor.spec).

Why a subprocess and not a thread: NiceGUI's own ``ui.run()`` blocks the
calling event loop for the life of the app and offers no clean in-process
stop — a subprocess can be ``.terminate()``d from the launcher's own event
loop without tearing down the launcher itself.

Why routing through the OS browser (not pywebview) for the actual app: this
also sidesteps a real Windows bug — pywebview's WebView2 backend never fires
a save dialog for ``ui.download`` unless the host wires
``CoreWebView2.DownloadStarting`` itself, which pywebview doesn't do by
default. The launcher window stays a tiny native control panel; the real
app opens in the user's own browser, where downloads just work.

Frozen (PyInstaller) vs. dev re-invocation, both driven through this same
module so there is exactly one entry point either way:

- Frozen: ``sys.executable`` *is* the app bundle itself, so re-running it
  with no args re-enters this file's ``main()``. Setting ``VISOR_SUBPROCESS=1``
  in the child's environment tells that second ``main()`` to skip the
  launcher UI and run the existing hosted-mode ``visor.app.run()`` directly.
- Dev/source: ``sys.executable`` is a real interpreter, so the child is
  started as ``-m visor.launcher`` (not a bare script path — see
  visor/BUILD.md on why ``-m`` is required for ``visor.app`` too) with the
  repo root added to ``PYTHONPATH`` and set as ``cwd``, for the same reason.

Either way the child process hits this module's own ``main()`` again and
takes the ``VISOR_SUBPROCESS`` branch — ``visor.app``'s existing
``run()``/``main_page()`` logic is reused unchanged, never duplicated.
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from nicegui import app, run, ui

logger = logging.getLogger(__name__)

DEFAULT_PORT = int(os.environ.get("VISOR_PORT", "8080"))
HEALTH_CHECK_TIMEOUT_S = 10.0
HEALTH_CHECK_INTERVAL_S = 0.3
TERMINATE_GRACE_S = 5.0

_REPO_ROOT = Path(__file__).resolve().parent.parent


def is_port_free(port: int, host: str = "0.0.0.0") -> bool:
    """A real bind-and-release check, not a guess — matches the interface
    the hosted server itself binds to (visor.app.run()'s host="0.0.0.0")."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
        return True


@dataclass
class SubprocessSpec:
    """Pure description of how to spawn the hosted server — kept separate
    from any actual ``subprocess.Popen`` call so it's testable without ever
    spawning a real process."""

    argv: list[str]
    env: dict[str, str]
    cwd: str | None


def build_subprocess_spec(
    port: int, *, frozen: bool, executable: str, repo_root: Path = _REPO_ROOT
) -> SubprocessSpec:
    """Builds the argv/env/cwd for re-invoking this same app as the hosted
    server. See the module docstring for the frozen-vs-dev distinction."""
    env = {"VISOR_SUBPROCESS": "1", "VISOR_PORT": str(port)}
    if frozen:
        return SubprocessSpec(argv=[executable], env=env, cwd=None)

    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{repo_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(repo_root)
    )
    return SubprocessSpec(
        argv=[executable, "-m", "visor.launcher"], env=env, cwd=str(repo_root)
    )


def wait_for_health(port: int, timeout_s: float = HEALTH_CHECK_TIMEOUT_S) -> bool:
    """Polls GET / until it responds or *timeout_s* elapses — so the caller
    never opens a browser tab to a connection-refused page while the server
    is still booting."""
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0):  # noqa: S310 - localhost only
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(HEALTH_CHECK_INTERVAL_S)
    return False


class ServerController:
    """Owns the at-most-one hosted-visor subprocess, so Start/Stop/Restart
    and the launcher-window-closed cleanup handler all share one source of
    truth for "is something running right now."""

    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None
        self.port: int | None = None

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, port: int) -> str | None:
        """Spawns the hosted server on *port*. Returns an error message on
        failure, or None on success. A no-op (returns None) if a server is
        already running."""
        if self.is_running:
            return None
        if not is_port_free(port):
            return f"Port {port} is already in use."

        spec = build_subprocess_spec(
            port, frozen=getattr(sys, "frozen", False), executable=sys.executable
        )
        env = {**os.environ, **spec.env}
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, no user input
                spec.argv,
                env=env,
                cwd=spec.cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.exception("Failed to start hosted visor server")
            return f"Failed to start server: {exc}"

        self.process = process
        self.port = port
        if not wait_for_health(port):
            self.stop()
            return "Server did not respond to a health check in time."
        return None

    def stop(self) -> None:
        """Terminates the running subprocess, falling back to a hard kill if
        it doesn't exit within TERMINATE_GRACE_S. A no-op if nothing is
        running."""
        process = self.process
        if process is None:
            return
        self.process = None
        self.port = None
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=TERMINATE_GRACE_S)
        except subprocess.TimeoutExpired:
            process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=TERMINATE_GRACE_S)


_controller = ServerController()


def _build_launcher_page(default_port: int) -> None:
    with ui.column().classes("q-pa-md gap-2"):
        ui.label("Visor Launcher").classes("text-h5")

        port_input = (
            ui.number("Port", value=default_port, min=1, max=65535, precision=0)
            .classes("w-full")
            .mark("launcher-port")
        )
        status_label = ui.label("Status: stopped").mark("launcher-status")
        url_label = ui.label("").mark("launcher-url")

        def _selected_port() -> int | None:
            value = port_input.value
            if value is None:
                ui.notify("Enter a port number first.", type="negative")
                return None
            return int(value)

        async def _on_start() -> None:
            if _controller.is_running:
                return
            port = _selected_port()
            if port is None:
                return
            error = await run.io_bound(_controller.start, port)
            if error:
                status_label.text = f"Status: error — {error}"
                ui.notify(error, type="negative")
            else:
                webbrowser.open(f"http://localhost:{port}")
            _refresh_controls()

        async def _on_stop() -> None:
            if not _controller.is_running:
                return
            await run.io_bound(_controller.stop)
            _refresh_controls()

        async def _on_restart() -> None:
            if not _controller.is_running:
                return
            port = _selected_port()
            if port is None:
                return
            await run.io_bound(_controller.stop)
            error = await run.io_bound(_controller.start, port)
            if error:
                status_label.text = f"Status: error — {error}"
                ui.notify(error, type="negative")
            else:
                webbrowser.open(f"http://localhost:{port}")
            _refresh_controls()

        with ui.row().classes("gap-2"):
            start_btn = ui.button("Start", on_click=_on_start).mark("launcher-start")
            restart_btn = ui.button("Restart", on_click=_on_restart).mark("launcher-restart")
            stop_btn = ui.button("Stop", on_click=_on_stop).mark("launcher-stop")

        def _refresh_controls() -> None:
            running = _controller.is_running
            start_btn.set_enabled(not running)
            restart_btn.set_enabled(running)
            stop_btn.set_enabled(running)
            port_input.set_enabled(not running)
            if running:
                status_label.text = "Status: running"
                url_label.text = f"http://localhost:{_controller.port}"
            else:
                if status_label.text == "Status: running":
                    status_label.text = "Status: stopped"
                url_label.text = ""

        ui.timer(1.0, _refresh_controls)
        _refresh_controls()


def run_launcher_ui() -> None:
    ui.page("/")(lambda: _build_launcher_page(DEFAULT_PORT))
    app.on_shutdown(_controller.stop)
    ui.run(
        title="Visor Launcher",
        native=True,
        reload=False,
        show=True,
        window_size=(420, 260),
    )


def main() -> None:
    if os.environ.get("VISOR_SUBPROCESS") == "1":
        os.environ["VISOR_NATIVE"] = "0"
        from visor.app import run as run_hosted_app

        run_hosted_app()
        return
    run_launcher_ui()


if __name__ in {"__main__", "__mp_main__"}:
    main()
