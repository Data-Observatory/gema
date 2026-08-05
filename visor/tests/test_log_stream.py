"""Tests for visor.log_stream — pure stdlib logging capture, no NiceGUI."""

from __future__ import annotations

import logging

from visor.log_stream import drain, start_capturing, stop_capturing


class TestStartCapturing:
    def test_captures_a_record_from_the_named_logger(self) -> None:
        capture = start_capturing("test_visor_capture_a")
        try:
            logging.getLogger("test_visor_capture_a").info("hello")
            lines = drain(capture.queue)
        finally:
            stop_capturing(capture)
        assert len(lines) == 1
        assert "hello" in lines[0]

    def test_captures_descendant_loggers_via_propagation(self) -> None:
        capture = start_capturing("test_visor_capture_b")
        try:
            logging.getLogger("test_visor_capture_b.child").warning("child warning")
            lines = drain(capture.queue)
        finally:
            stop_capturing(capture)
        assert len(lines) == 1
        assert "child warning" in lines[0]

    def test_raises_effective_level_to_info_when_higher(self) -> None:
        target = logging.getLogger("test_visor_capture_c")
        target.setLevel(logging.WARNING)
        capture = start_capturing("test_visor_capture_c")
        try:
            assert target.level == logging.INFO
            target.info("should be captured")
            lines = drain(capture.queue)
        finally:
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
        stop_capturing(capture)
        target = logging.getLogger("test_visor_capture_e")
        target.info("not captured anymore")
        assert drain(capture.queue) == []


class TestDrain:
    def test_drain_empties_the_queue_without_blocking(self) -> None:
        capture = start_capturing("test_visor_capture_f")
        try:
            logger = logging.getLogger("test_visor_capture_f")
            logger.info("one")
            logger.info("two")
            first = drain(capture.queue)
            second = drain(capture.queue)
        finally:
            stop_capturing(capture)
        assert len(first) == 2
        assert second == []
