"""Shutdown mid-batch (SIGTERM / docker compose stop): nothing new is claimed, interrupted
records go back to ``pending`` (never ``failed``), and a stored PID means no duplicate."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from intake_app.errors import PermanentError
from intake_app.gema_runner import BuiltPayload
from intake_app.processor import SHUTDOWN_NOTE, BatchProcessor, Defaults, is_shutdown_error
from intake_app.store import DONE, FAILED, PENDING, PROCESSING, Store
from intake_helpers import FakeBuilder, FakePublisher, add, make_dataset_json

DEFAULTS = Defaults(contact_email="workshop@example.test", contact_name="Workshop")


class GatedBuilder(FakeBuilder):
    """build_payload blocks until ``gate`` is set; ``calls`` records entries."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()

    def build_payload(self, url: str, hints: str) -> BuiltPayload:
        with self._lock:
            self.calls.append(url)
        self.gate.wait(10)
        return BuiltPayload(dataset_json=make_dataset_json())


class GatedPublisher(FakePublisher):
    """publish blocks until ``gate`` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()
        self.publish_calls = 0

    def publish(self, pid: str) -> None:
        with self._lock:
            self.publish_calls += 1
        self.gate.wait(10)
        super().publish(pid)


def make(store: Store, builder: Any, publisher: Any, workers: int = 2) -> BatchProcessor:
    return BatchProcessor(
        store,
        builder,
        publisher,
        DEFAULTS,
        workers=workers,
        record_timeout=30,
        retry_delay=0.0,
        sleep=lambda _s: None,
    )


def wait_until(predicate: Any, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def test_shutdown_mid_batch_returns_records_to_pending_and_claims_nothing_new(
    store: Store,
) -> None:
    ids = [add(store, f"https://ok.org/{i}") for i in range(6)]
    builder, publisher = GatedBuilder(), FakePublisher()
    processor = make(store, builder, publisher, workers=2)
    processor.start(PENDING)
    wait_until(lambda: len(builder.calls) == 2)

    processor.shutdown(grace=0.2)  # in-flight work never finishes in time

    assert store.counts() == {"pending": 6, "processing": 0, "done": 0, "failed": 0}
    in_flight = set(builder.calls)
    assert len(in_flight) == 2
    for rid in ids:
        rec = store.get(rid)
        assert rec is not None and rec.status == PENDING
        # only the two interrupted ones carry the note; the queued ones were never touched
        assert rec.error == (SHUTDOWN_NOTE if rec.url in in_flight else "")

    # The abandoned GEMA! calls finish later: they must create nothing, claim nothing.
    builder.gate.set()
    processor.wait(5)
    time.sleep(0.3)
    assert len(builder.calls) == 2
    assert publisher.created == []
    assert store.counts()["pending"] == 6
    assert processor.start(PENDING) is None  # no new batch once stopping


def test_in_flight_records_that_finish_within_grace_are_done(store: Store) -> None:
    ids = [add(store, f"https://ok.org/{i}") for i in range(5)]
    builder = FakeBuilder()
    builder.delay = 0.3
    publisher = FakePublisher()
    processor = make(store, builder, publisher, workers=2)
    processor.start(PENDING)
    wait_until(lambda: builder.active == 2)

    assert processor.shutdown(grace=5) == 0

    assert store.counts() == {"pending": 3, "processing": 0, "done": 2, "failed": 0}
    assert len(builder.calls) == 2 and len(publisher.created) == 2
    assert all(store.get(r).error == "" for r in ids)  # type: ignore[union-attr]


def test_interpreter_shutdown_error_goes_back_to_pending_not_failed(store: Store) -> None:
    class DyingBuilder(FakeBuilder):
        def build_payload(self, url: str, hints: str) -> BuiltPayload:
            # what GemaRunner raises when the pipeline reports the RuntimeError as a string
            raise PermanentError("cannot schedule new futures after interpreter shutdown")

    rid = add(store, "https://ok.org/x")
    processor = make(store, DyingBuilder(), FakePublisher())
    assert processor.process_record(rid) == PENDING
    rec = store.get(rid)
    assert rec is not None and rec.status == PENDING and rec.error == SHUTDOWN_NOTE


def test_raw_runtime_error_from_executor_is_recognized() -> None:
    assert is_shutdown_error(RuntimeError("cannot schedule new futures after shutdown"))
    wrapped = PermanentError("GEMA! failed")
    wrapped.__cause__ = RuntimeError("cannot schedule new futures after interpreter shutdown")
    assert is_shutdown_error(wrapped)
    assert not is_shutdown_error(PermanentError("URL returned HTTP 404"))


def test_stored_pid_survives_shutdown_and_next_run_does_not_duplicate(store: Store) -> None:
    rid = add(store, "https://ok.org/x")
    publisher = GatedPublisher()
    processor = make(store, FakeBuilder(), publisher)
    processor.start(PENDING)
    wait_until(lambda: publisher.publish_calls == 1)  # dataset created, PID stored

    assert processor.shutdown(grace=0.2) == 0  # the worker put it back itself
    rec = store.get(rid)
    assert rec is not None and rec.status == PENDING
    assert rec.dataverse_pid == "perma:DV/T1"
    publisher.gate.set()
    processor.wait(5)
    time.sleep(0.2)
    assert store.get(rid).status == PENDING  # type: ignore[union-attr]

    # "Restart": a fresh processor on the same store finishes it publish-only.
    builder2 = FakeBuilder()
    fresh = make(store, builder2, publisher)
    assert fresh.process_record(rid) == DONE
    assert builder2.calls == []
    assert len(publisher.created) == 1


def test_shutdown_with_no_batch_is_harmless(store: Store) -> None:
    rid = add(store, "https://ok.org/x")
    processor = make(store, FakeBuilder(), FakePublisher())
    assert processor.shutdown(grace=1) == 0
    assert processor.process_record(rid) == "skipped"
    assert store.get(rid).status == PENDING  # type: ignore[union-attr]


def test_genuine_failure_during_grace_still_fails(store: Store) -> None:
    broken = add(store, "https://broken.org/x")
    builder = FakeBuilder()
    builder.delay = 0.2
    processor = make(store, builder, FakePublisher())
    processor.start(PENDING)
    wait_until(lambda: builder.active == 1)
    processor.shutdown(grace=5)
    assert store.get(broken).status == FAILED  # type: ignore[union-attr]
    assert store.counts()[PROCESSING] == 0


def test_store_release_only_touches_processing(store: Store) -> None:
    rid = add(store, "https://ok.org/x")
    assert not store.release(rid, "x")  # pending: untouched
    store.claim(rid, PENDING)
    store.set_pid(rid, "perma:DV/1", "http://dv/1")
    assert store.release(rid, "x")
    rec = store.get(rid)
    assert rec is not None and rec.status == PENDING and rec.dataverse_pid == "perma:DV/1"


def test_app_lifespan_shutdown_stops_the_processor(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("multipart")
    pytest.importorskip("jinja2")
    from fastapi.testclient import TestClient
    from test_web import make_settings

    from intake_app.web import create_app

    settings = make_settings(tmp_path, shutdown_grace=0)
    st = Store(settings.db_path)
    st.init()
    processor = make(st, FakeBuilder(), FakePublisher())
    with TestClient(create_app(settings, st, processor)) as client:
        assert client.get("/").status_code == 200
        assert not processor.is_stopping()
    assert processor.is_stopping()
