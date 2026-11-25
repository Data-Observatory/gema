"""Batch processing: claim -> GEMA! -> Dataverse create -> publish, per record, in a pool.

Guarantees:
* one record failing (exception, timeout, bad URL) only marks that record ``failed``;
* ``done`` records are never claimed, so never re-run or re-uploaded;
* the Dataverse PID is stored the moment the dataset exists, so a retry (automatic, or the
  admin's "Retry failed") of a half-finished record only publishes -- no duplicate dataset;
* the per-record timeout is a deadline on the record's worker thread; Python cannot kill a
  thread, so a timed-out attempt is *abandoned* (flagged so it writes nothing further,
  other than the PID of a dataset it may still manage to create, which is exactly what
  keeps the next retry duplicate-free).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from intake_app.dataverse import Publisher, finalize_payload
from intake_app.errors import PermanentError, StepError, TransientError
from intake_app.gema_runner import PayloadBuilder
from intake_app.store import FAILED, PENDING, Resource, Store

logger = logging.getLogger(__name__)

MAX_ERROR_LEN = 300
ATTEMPTS = 2  # first try + one automatic retry for transient errors


@dataclass(frozen=True)
class Defaults:
    contact_email: str
    contact_name: str


def short_error(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    if not isinstance(exc, StepError):
        text = f"{type(exc).__name__}: {text}"
    return " ".join(text.split())[:MAX_ERROR_LEN]


class BatchProcessor:
    def __init__(
        self,
        store: Store,
        builder: PayloadBuilder,
        publisher: Publisher,
        defaults: Defaults,
        *,
        workers: int = 4,
        record_timeout: float = 300,
        retry_delay: float = 3.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store = store
        self._builder = builder
        self._publisher = publisher
        self._defaults = defaults
        self._workers = workers
        self._timeout = record_timeout
        self._retry_delay = retry_delay
        self._sleep = sleep
        self._run_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # -- batch control -------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._run_lock.locked()

    def start(self, from_status: str) -> int | None:
        """Start a background batch over every record currently in *from_status*
        (``pending`` for Process, ``failed`` for Retry failed). Returns the number of
        records queued, or None if a batch is already running. Never blocks."""
        if not self._run_lock.acquire(blocking=False):
            return None
        ids = self._store.ids_with_status(from_status)
        self._thread = threading.Thread(
            target=self._run_batch, args=(ids, from_status), name="intake-batch", daemon=True
        )
        self._thread.start()
        return len(ids)

    def wait(self, timeout: float | None = None) -> None:
        """Block until the current batch ends (tests)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run_batch(self, ids: list[int], from_status: str) -> None:
        started = time.monotonic()
        logger.info(
            "batch start: %d record(s) from %r, %d worker(s)", len(ids), from_status, self._workers
        )
        try:
            with ThreadPoolExecutor(
                max_workers=self._workers, thread_name_prefix="intake-w"
            ) as pool:
                list(pool.map(lambda rid: self.process_record(rid, from_status), ids))
        except Exception:
            logger.exception("batch crashed")
        finally:
            counts = self._store.counts()
            logger.info("batch end after %.0fs: %s", time.monotonic() - started, counts)
            self._run_lock.release()

    # -- one record ----------------------------------------------------------------------

    def process_record(self, rid: int, from_status: str = PENDING) -> str:
        """Process one record end to end. Never raises. Returns the final status, or the
        string ``skipped`` if the record could not be claimed (deleted, already running or
        done)."""
        record = self._store.claim(rid, from_status)
        if record is None:
            logger.info("record %s: not claimable from %r, skipped", rid, from_status)
            return "skipped"
        logger.info("record %s: start (%s, by %s)", rid, record.url, record.pseudonym)

        deadline = time.monotonic() + self._timeout
        cancel = threading.Event()
        try:
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    self._attempt_with_deadline(rid, deadline, cancel)
                except TransientError as exc:
                    if attempt == ATTEMPTS or time.monotonic() >= deadline:
                        raise
                    logger.warning("record %s: transient error (%s), retrying", rid, exc)
                    self._sleep(self._retry_delay)
                    continue
                self._store.mark_done(rid)
                logger.info("record %s: done", rid)
                return "done"
        except Exception as exc:  # noqa: BLE001 - one record must never abort the batch
            cancel.set()
            message = short_error(exc)
            logger.error("record %s: failed: %s", rid, message)
            try:
                self._store.mark_failed(rid, message)
            except Exception:
                logger.exception("record %s: could not store failure", rid)
        return FAILED

    def _attempt_with_deadline(self, rid: int, deadline: float, cancel: threading.Event) -> None:
        outcome: list[BaseException] = []

        def target() -> None:
            try:
                self._attempt(rid, cancel)
            except BaseException as exc:  # noqa: BLE001 - relayed to the caller below
                outcome.append(exc)

        thread = threading.Thread(target=target, name=f"intake-rec-{rid}", daemon=True)
        thread.start()
        thread.join(max(deadline - time.monotonic(), 0.0))
        if thread.is_alive():
            cancel.set()
            raise PermanentError(f"timed out after {self._timeout:.0f}s")
        if outcome:
            raise outcome[0]

    def _attempt(self, rid: int, cancel: threading.Event) -> None:
        record = self._store.get(rid)
        if record is None:
            raise PermanentError("record was deleted while processing")
        pid = record.dataverse_pid
        if not pid:
            pid = self._create(record, cancel)
        if cancel.is_set():
            return
        self._publisher.publish(pid)

    def _create(self, record: Resource, cancel: threading.Event) -> str:
        built = self._builder.build_payload(record.url, record.hints)
        for warning in built.warnings:
            logger.info("record %s: warning: %s", record.id, warning)
        payload = finalize_payload(
            built.dataset_json,
            pseudonym=record.pseudonym,
            default_contact_email=self._defaults.contact_email,
            default_contact_name=self._defaults.contact_name,
        )
        if cancel.is_set():  # timed out while GEMA! was running: do not create anything
            raise PermanentError("abandoned after timeout")
        pid = self._publisher.create_dataset(payload)
        # Store at once, even if abandoned meanwhile: the retry then publishes this dataset.
        self._store.set_pid(record.id, pid, self._publisher.dataset_url(pid))
        return pid
