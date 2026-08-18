"""Tests for visor.log_stream — pure stdlib logging capture, no NiceGUI."""

from __future__ import annotations

import logging

from visor.log_stream import activate_run, deactivate_run, drain, start_capturing, stop_capturing


class TestStartCapturing:
    def test_captures_a_record_from_the_named_logger(self) -> None:
        capture = start_capturing("test_visor_capture_a")
        token = activate_run(capture.run_id)
        try:
            logging.getLogger("test_visor_capture_a").info("hello")
            lines = drain(capture.queue)
        finally:
            deactivate_run(token)
            stop_capturing(capture)
        assert len(lines) == 1
        assert "hello" in lines[0]

    def test_captures_descendant_loggers_via_propagation(self) -> None:
        capture = start_capturing("test_visor_capture_b")
        token = activate_run(capture.run_id)
        try:
            logging.getLogger("test_visor_capture_b.child").warning("child warning")
            lines = drain(capture.queue)
        finally:
            deactivate_run(token)
            stop_capturing(capture)
        assert len(lines) == 1
        assert "child warning" in lines[0]

    def test_raises_effective_level_to_info_when_higher(self) -> None:
        target = logging.getLogger("test_visor_capture_c")
        target.setLevel(logging.WARNING)
        capture = start_capturing("test_visor_capture_c")
        token = activate_run(capture.run_id)
        try:
            assert target.level == logging.INFO
            target.info("should be captured")
            lines = drain(capture.queue)
        finally:
            deactivate_run(token)
            stop_capturing(capture)
        assert len(lines) == 1

    def test_stop_capturing_restores_previous_level(self) -> None:
        target = logging.getLogger("test_visor_capture_d")
        target.setLevel(logging.WARNING)
        capture = start_capturing("test_visor_capture_d")
        stop_capturing(capture)
        assert target.level == logging.WARNING

    def test_stop_capturing_removes_the_handler(self) -> None:
        capture = start_capturing("test_visor_capture_e")
        token = activate_run(capture.run_id)
        stop_capturing(capture)
        target = logging.getLogger("test_visor_capture_e")
        target.info("not captured anymore")
        deactivate_run(token)
        assert drain(capture.queue) == []

    def test_records_from_an_inactive_run_are_dropped(self) -> None:
        """The actual regression this module exists to fix: two concurrent
        hosted sessions' captures are both attached to the same shared
        logger, so a handler must ignore any record emitted by a thread
        that isn't marked as executing *its own* run_id -- otherwise one
        session's "Show details" log includes another session's lines."""
        capture = start_capturing("test_visor_capture_g")
        try:
            # No activate_run() call at all -- this thread is executing
            # nobody's run as far as the handler is concerned.
            logging.getLogger("test_visor_capture_g").info("someone else's line")
            lines = drain(capture.queue)
        finally:
            stop_capturing(capture)
        assert lines == []

    def test_records_from_a_different_active_run_are_dropped(self) -> None:
        capture_a = start_capturing("test_visor_capture_h")
        capture_b = start_capturing("test_visor_capture_h")
        token = activate_run(capture_b.run_id)
        try:
            logging.getLogger("test_visor_capture_h").info("belongs to run B")
            lines_a = drain(capture_a.queue)
            lines_b = drain(capture_b.queue)
        finally:
            deactivate_run(token)
            stop_capturing(capture_b)
            stop_capturing(capture_a)
        assert lines_a == []
        assert len(lines_b) == 1


class TestDrain:
    def test_drain_empties_the_queue_without_blocking(self) -> None:
        capture = start_capturing("test_visor_capture_f")
        token = activate_run(capture.run_id)
        try:
            logger = logging.getLogger("test_visor_capture_f")
            logger.info("one")
            logger.info("two")
            first = drain(capture.queue)
            second = drain(capture.queue)
        finally:
            deactivate_run(token)
            stop_capturing(capture)
        assert len(first) == 2
        assert second == []
