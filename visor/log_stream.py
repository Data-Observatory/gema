"""Thread-safe capture of Python logging records, for live display in the UI.

Pipeline.run() executes on a background thread (offloaded via run.io_bound
so NiceGUI's event loop isn't blocked — see run_page.py) — logging.Handler.
emit() therefore runs on that same worker thread. Records are handed off
through a queue.Queue (thread-safe) rather than touching any NiceGUI
element directly from a non-UI thread; the UI side drains the queue on a
ui.timer, which runs on the event loop.

Multiple hosted sessions can have pipeline runs in flight at once, and they
all share the one "metadata_enricher" logger — start_capturing() attaches a
handler per session, but every handler attached to that logger receives
*every* record any session's run emits (that's how logging propagation
works), not just its own. A per-record run-id check (via a contextvar,
propagated into orchestrator.py's per-wave worker threads) is what keeps
each session's capture to its own lines; see activate_run()'s docstring.

Pure stdlib logic, deliberately free of any NiceGUI import, so it's
testable without a UI.
"""

from __future__ import annotations

import contextvars
import logging
import queue
import uuid
from dataclasses import dataclass

# Sentinel default (rather than None) so a run that's forgotten to activate
# itself can never accidentally match a handler for a *different* run whose
# run_id happens to be None -- every real run_id is a fresh uuid4 hex string.
_NO_RUN = "no-run-active"
_current_run_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "visor_current_run_id", default=_NO_RUN
)


def activate_run(run_id: str) -> contextvars.Token[str]:
    """Mark the calling thread as executing *run_id* -- call at the very
    start of the pipeline call on whatever thread run.io_bound hands it,
    and orchestrator.py's per-wave ThreadPoolExecutor propagates this into
    each agent's own worker thread via contextvars.copy_context() (plain
    thread-locals don't cross thread boundaries; a copied context does).
    Returns a token for deactivate_run() to restore the previous value --
    thread pool workers are reused across unrelated later calls, so this
    must not leak past the run it belongs to."""
    return _current_run_id.set(run_id)


def deactivate_run(token: contextvars.Token[str]) -> None:
    _current_run_id.reset(token)


class QueueLogHandler(logging.Handler):
    """Formats each record and puts the line on a thread-safe queue --
    but only if it was emitted by a thread executing this handler's own
    run_id (see module docstring)."""

    def __init__(self, line_queue: queue.Queue[str], run_id: str) -> None:
        super().__init__(level=logging.INFO)
        self._queue = line_queue
        self._run_id = run_id
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        if _current_run_id.get() != self._run_id:
            return
        self._queue.put(self.format(record))


@dataclass
class LogCapture:
    logger: logging.Logger
    handler: QueueLogHandler
    queue: queue.Queue[str]
    previous_level: int
    run_id: str


def start_capturing(logger_name: str = "metadata_enricher") -> LogCapture:
    """Attach a QueueLogHandler to *logger_name* — capturing it and every
    descendant logger via normal propagation (pipeline/orchestrator/agents
    all log under this namespace). Temporarily lowers the logger's own
    level to INFO if it was set higher, since a handler never sees records
    the logger itself filters out first; stop_capturing restores it.

    The returned LogCapture.run_id must be passed through to whatever
    actually runs the pipeline (see visor.glue.run_single's run_id param)
    and activated there via activate_run() — this call alone only sets up
    the filter, it doesn't mark any thread as "this run" yet."""
    run_id = uuid.uuid4().hex
    line_queue: queue.Queue[str] = queue.Queue()
    handler = QueueLogHandler(line_queue, run_id)
    target_logger = logging.getLogger(logger_name)
    previous_level = target_logger.level
    target_logger.addHandler(handler)
    if target_logger.level == logging.NOTSET or target_logger.level > logging.INFO:
        target_logger.setLevel(logging.INFO)
    return LogCapture(target_logger, handler, line_queue, previous_level, run_id)


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
