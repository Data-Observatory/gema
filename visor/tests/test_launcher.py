"""Tests for visor.launcher — the port-free check and the frozen-vs-dev
subprocess-argument-building logic, in isolation.

Deliberately does not spawn a real subprocess or open a real window (see the
module's own docstring on why full lifecycle testing is out of scope here) —
only what's realistically unit-testable without either.
"""

from __future__ import annotations

import os
import socket
import sys

import visor.launcher as launcher


class TestIsPortFree:
    def test_free_port_reports_free(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("0.0.0.0", 0))
            free_port = probe.getsockname()[1]
        assert launcher.is_port_free(free_port) is True

    def test_busy_port_reports_busy(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            occupied.bind(("0.0.0.0", 0))
            occupied.listen(1)
            port = occupied.getsockname()[1]
            assert launcher.is_port_free(port) is False


class TestBuildSubprocessSpec:
    def test_frozen_reinvokes_the_running_executable(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        spec = launcher.build_subprocess_spec(
            8123, frozen=getattr(sys, "frozen", False), executable="/opt/Visor/Visor"
        )
        assert spec.argv == ["/opt/Visor/Visor"]
        assert spec.env["VISOR_SUBPROCESS"] == "1"
        assert spec.env["VISOR_PORT"] == "8123"
        assert "PYTHONPATH" not in spec.env
        assert spec.cwd is None

    def test_dev_reinvokes_via_module_flag(self, monkeypatch, tmp_path) -> None:
        monkeypatch.delattr(sys, "frozen", raising=False)
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        spec = launcher.build_subprocess_spec(
            9001,
            frozen=getattr(sys, "frozen", False),
            executable="/usr/bin/python3",
            repo_root=repo_root,
        )
        assert spec.argv == ["/usr/bin/python3", "-m", "visor.launcher"]
        assert spec.env["VISOR_SUBPROCESS"] == "1"
        assert spec.env["VISOR_PORT"] == "9001"
        assert spec.env["PYTHONPATH"] == str(repo_root)
        assert spec.cwd == str(repo_root)

    def test_dev_preserves_existing_pythonpath(self, monkeypatch, tmp_path) -> None:
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.setenv("PYTHONPATH", "/some/other/path")
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        spec = launcher.build_subprocess_spec(
            9002, frozen=False, executable="/usr/bin/python3", repo_root=repo_root
        )
        assert spec.env["PYTHONPATH"] == f"{repo_root}{os.pathsep}/some/other/path"


class TestServerControllerNoSubprocess:
    """Guards the no-op contracts without ever spawning a real process."""

    def test_stop_is_a_noop_when_nothing_running(self) -> None:
        controller = launcher.ServerController()
        controller.stop()  # must not raise
        assert controller.is_running is False

    def test_start_is_a_noop_when_already_running(self, monkeypatch) -> None:
        controller = launcher.ServerController()

        class _FakeProcess:
            def poll(self) -> int | None:
                return None

        controller.process = _FakeProcess()  # type: ignore[assignment]

        def _fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("start() should be a no-op while already running")

        monkeypatch.setattr(launcher, "is_port_free", _fail_if_called)
        assert controller.start(8080) is None

    def test_start_reports_busy_port_without_spawning(self, monkeypatch) -> None:
        controller = launcher.ServerController()
        monkeypatch.setattr(launcher, "is_port_free", lambda port, host="0.0.0.0": False)

        def _fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("must not attempt to spawn when the port is busy")

        monkeypatch.setattr(launcher.subprocess, "Popen", _fail_if_called)
        error = controller.start(8080)
        assert error is not None
        assert "already in use" in error
        assert controller.is_running is False
