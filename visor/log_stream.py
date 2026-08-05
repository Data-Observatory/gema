"""Thread-safe capture of Python logging records, for live display in the UI.

Pipeline.run() executes on a background thread (offloaded via run.io_bound
so NiceGUI's event loop isn't blocked — see run_page.py) — logging.Handler.
emit() therefore runs on that same worker thread. Records are handed off
through a queue.Queue (thread-safe) rather than touching any NiceGUI
element directly from a non-UI thread; the UI side drains the queue on a
ui.timer, which runs on the event loop.

Pure stdlib logic, deliberately free of any NiceGUI import, so it's
testable without a UI.
"""

from __future__ import annotations

import logging
import queue
from dataclasses import dataclass


class QueueLogHandler(logging.Handler):
    """Formats each record and puts the line on a thread-safe queue."""

    def __init__(self, line_queue: queue.Queue[str]) -> None:
        super().__init__(level=logging.INFO)
        self._queue = line_queue
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self._queue.put(self.format(record))


@dataclass
class LogCapture:
    logger: logging.Logger
    handler: QueueLogHandler
    queue: queue.Queue[str]
    previous_level: int


def start_capturing(logger_name: str = "metadata_enricher") -> LogCapture:
    """Attach a QueueLogHandler to *logger_name* — capturing it and every
    descendant logger via normal propagation (pipeline/orchestrator/agents
    all log under this namespace). Temporarily lowers the logger's own
    level to INFO if it was set higher, since a handler never sees records
    the logger itself filters out first; stop_capturing restores it."""
    line_queue: queue.Queue[str] = queue.Queue()
    handler = QueueLogHandler(line_queue)
    target_logger = logging.getLogger(logger_name)
    previous_level = target_logger.level
    target_logger.addHandler(handler)
    if target_logger.level == logging.NOTSET or target_logger.level > logging.INFO:
        target_logger.setLevel(logging.INFO)
    return LogCapture(target_logger, handler, line_queue, previous_level)


def stop_capturing(capture: LogCapture) -> None:
    capture.logger.removeHandler(capture.handler)
    capture.logger.setLevel(capture.previous_level)


def drain(line_queue: queue.Queue[str]) -> list[str]:
    """Pop everything currently queued, without blocking."""
    lines: list[str] = []
    while True:
        try:
            lines.append(line_queue.get_nowait())
        except queue.Empty:
            break
    return lines
