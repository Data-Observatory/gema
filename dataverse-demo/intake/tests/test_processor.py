from __future__ import annotations

import json

from intake_app.dataverse import finalize_payload
from intake_app.processor import BatchProcessor, Defaults
from intake_app.store import DONE, FAILED, PENDING, Store
from intake_helpers import FakeBuilder, FakePublisher, add, make_dataset_json

DEFAULTS = Defaults(contact_email="workshop@example.test", contact_name="Workshop")


def make_processor(
    store: Store,
    builder: FakeBuilder | None = None,
    publisher: FakePublisher | None = None,
    **kwargs: float,
) -> tuple[BatchProcessor, FakeBuilder, FakePublisher]:
    builder = builder or FakeBuilder()
    publisher = publisher or FakePublisher()
    options = {"workers": 4, "record_timeout": 30, "retry_delay": 0.0, **kwargs}
    processor = BatchProcessor(
        store,
        builder,
        publisher,
        DEFAULTS,
        workers=int(options["workers"]),
        record_timeout=options["record_timeout"],
        retry_delay=options["retry_delay"],
        sleep=lambda _s: None,
    )
    return processor, builder, publisher


def run_batch(processor: BatchProcessor, from_status: str = PENDING) -> int | None:
    queued = processor.start(from_status)
    processor.wait(30)
    return queued


def test_batch_one_failure_does_not_stop_the_others(store: Store) -> None:
    ids = {n: add(store, f"https://ok.org/{n}", f"user{n}") for n in range(15)}
    broken = add(store, "https://broken.org/404", "zoe")
    processor, _builder, publisher = make_processor(store, workers=4)

    assert run_batch(processor) == 16

    rows = {r.id: r for r in store.all_records()}
    assert rows[broken].status == FAILED
    assert rows[broken].error == "URL returned HTTP 404"
    assert rows[broken].dataverse_pid == ""
    for rid in ids.values():
        rec = rows[rid]
        assert rec.status == DONE, rec
        assert rec.dataverse_pid.startswith("perma:DV/")
        assert rec.dataverse_url.endswith(rec.dataverse_pid)
    assert store.counts() == {"pending": 0, "processing": 0, "done": 15, "failed": 1}
    assert len(publisher.created) == 15
    assert sorted(publisher.published) == sorted(
        r.dataverse_pid for r in rows.values() if r.dataverse_pid
    )


def test_unexpected_exception_is_contained_and_message_is_short(store: Store) -> None:
    boom = add(store, "https://boom.org/x")
    fine = add(store, "https://fine.org/x")
    processor, *_ = make_processor(store)
    run_batch(processor)
    assert store.get(boom).status == FAILED  # type: ignore[union-attr]
    assert "RuntimeError" in store.get(boom).error  # type: ignore[union-attr]
    assert len(store.get(boom).error) <= 300  # type: ignore[union-attr]
    assert store.get(fine).status == DONE  # type: ignore[union-attr]


def test_runs_records_in_parallel_up_to_worker_count(store: Store) -> None:
    for i in range(8):
        add(store, f"https://ok.org/{i}")
    builder = FakeBuilder()
    builder.delay = 0.15
    processor, *_ = make_processor(store, builder=builder, workers=4)
    run_batch(processor)
    assert 2 <= builder.max_active <= 4
    assert store.counts()["done"] == 8


def test_done_records_are_never_rerun_or_reuploaded(store: Store) -> None:
    rid = add(store, "https://ok.org/x")
    processor, builder, publisher = make_processor(store)
    run_batch(processor)
    assert store.get(rid).status == DONE  # type: ignore[union-attr]

    assert run_batch(processor, PENDING) == 0  # Process: nothing pending
    assert run_batch(processor, FAILED) == 0  # Retry failed: nothing failed
    assert processor.process_record(rid, PENDING) == "skipped"
    assert processor.process_record(rid, FAILED) == "skipped"
    assert builder.calls == ["https://ok.org/x"]
    assert len(publisher.created) == 1


def test_retry_failed_reruns_only_failed(store: Store) -> None:
    ok = add(store, "https://ok.org/x")
    bad = add(store, "https://broken.org/x")
    processor, builder, publisher = make_processor(store)
    run_batch(processor)
    assert (store.get(ok).status, store.get(bad).status) == (DONE, FAILED)  # type: ignore[union-attr]
    builder.calls.clear()

    assert run_batch(processor, FAILED) == 1
    assert builder.calls == ["https://broken.org/x"]  # the done record was left alone
    assert store.get(bad).status == FAILED  # type: ignore[union-attr]
    assert len(publisher.created) == 1


def test_transient_error_is_retried_once_automatically(store: Store) -> None:
    rid = add(store, "https://flaky.org/x")
    processor, builder, publisher = make_processor(store)
    run_batch(processor)
    assert store.get(rid).status == DONE  # type: ignore[union-attr]
    assert builder.calls == ["https://flaky.org/x"] * 2
    assert len(publisher.created) == 1


def test_permanent_error_is_not_retried(store: Store) -> None:
    add(store, "https://broken.org/x")
    processor, builder, _ = make_processor(store)
    run_batch(processor)
    assert builder.calls == ["https://broken.org/x"]


def test_transient_error_gives_up_after_one_retry(store: Store) -> None:
    class AlwaysTransient(FakeBuilder):
        def build_payload(self, url: str, hints: str):  # type: ignore[no-untyped-def]
            self.calls.append(url)
            from intake_app.errors import TransientError

            raise TransientError("HTTP 503")

    rid = add(store, "https://x.org/x")
    builder = AlwaysTransient()
    processor, *_ = make_processor(store, builder=builder)
    run_batch(processor)
    assert len(builder.calls) == 2
    assert store.get(rid).status == FAILED  # type: ignore[union-attr]
    assert store.get(rid).error == "HTTP 503"  # type: ignore[union-attr]


def test_publish_failure_keeps_pid_and_retry_only_publishes(store: Store) -> None:
    """Half-finished record: dataset created, publish failed (twice, so the automatic retry
    is spent). 'Retry failed' must publish the existing dataset, not create another one."""
    rid = add(store, "https://ok.org/x")
    publisher = FakePublisher()
    processor, builder, _ = make_processor(store, publisher=publisher)
    attempts = {"n": 0}
    real_publish = publisher.publish

    def failing_publish(pid: str) -> None:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            from intake_app.errors import TransientError

            raise TransientError("publish dataset: Dataverse HTTP 503")
        real_publish(pid)

    publisher.publish = failing_publish  # type: ignore[method-assign]
    run_batch(processor)

    rec = store.get(rid)
    assert rec is not None and rec.status == FAILED
    assert rec.dataverse_pid == "perma:DV/T1"  # stored right after creation
    assert len(publisher.created) == 1

    run_batch(processor, FAILED)
    rec = store.get(rid)
    assert rec is not None and rec.status == DONE
    assert len(publisher.created) == 1  # still one dataset
    assert builder.calls == ["https://ok.org/x"]  # GEMA! not re-run either
    assert publisher.published == ["perma:DV/T1"]


def test_record_timeout_fails_only_that_record(store: Store) -> None:
    slow = add(store, "https://hang.org/x")
    fine = add(store, "https://ok.org/x")
    processor, _b, publisher = make_processor(store, record_timeout=0.3)
    run_batch(processor)
    assert store.get(slow).status == FAILED  # type: ignore[union-attr]
    assert "timed out" in store.get(slow).error  # type: ignore[union-attr]
    assert store.get(fine).status == DONE  # type: ignore[union-attr]
    assert len(publisher.created) == 1  # the timed-out record never created a dataset


def test_only_one_batch_at_a_time(store: Store) -> None:
    add(store, "https://ok.org/x")
    builder = FakeBuilder()
    builder.delay = 0.3
    processor, *_ = make_processor(store, builder=builder)
    assert processor.start(PENDING) == 1
    assert processor.is_running()
    assert processor.start(PENDING) is None  # busy
    processor.wait(30)
    assert not processor.is_running()


def test_deleted_while_queued_is_skipped(store: Store) -> None:
    keep = add(store, "https://ok.org/keep")
    gone = add(store, "https://ok.org/gone")
    processor, builder, _ = make_processor(store)
    assert store.delete(gone)
    assert processor.process_record(gone, PENDING) == "skipped"
    assert processor.process_record(keep, PENDING) == "done"
    assert builder.calls == ["https://ok.org/keep"]


def test_hints_reach_the_builder_and_pseudonym_does_not(store: Store) -> None:
    add(store, "https://ok.org/x", pseudonym="Capybara", hints="Published by the Ministry")
    processor, builder, publisher = make_processor(store)
    run_batch(processor)
    assert builder.hints["https://ok.org/x"] == "Published by the Ministry"
    payload = publisher.created[0]
    text = json.dumps(payload)
    assert "group:Capybara" in text
    fields = payload["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
    assert not any(f["typeName"] in ("author", "publisher", "depositor") for f in fields)


def test_finalize_payload_adds_group_keyword_and_default_contact() -> None:
    original = make_dataset_json()
    payload = finalize_payload(
        original,
        pseudonym="Ana",
        default_contact_email="c@example.test",
        default_contact_name="Workshop",
    )
    fields = {
        f["typeName"]: f for f in payload["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
    }
    keywords = [k["keywordValue"]["value"] for k in fields["keyword"]["value"]]
    assert keywords == ["ocean", "group:Ana"]
    contact = fields["datasetContact"]["value"][0]
    assert contact["datasetContactEmail"]["value"] == "c@example.test"
    assert contact["datasetContactName"]["value"] == "Workshop"
    # the input is not mutated
    assert json.dumps(original) == json.dumps(make_dataset_json())


def test_finalize_payload_keeps_a_real_contact_and_creates_keyword_field() -> None:
    data = make_dataset_json()
    fields = data["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
    fields[:] = [f for f in fields if f["typeName"] != "keyword"]
    contact = next(f for f in fields if f["typeName"] == "datasetContact")
    contact["value"][0]["datasetContactEmail"]["value"] = "real@example.org"
    contact["value"][0]["datasetContactName"]["value"] = "Real Person"

    out = finalize_payload(
        data, pseudonym="Bo", default_contact_email="c@example.test", default_contact_name="W"
    )
    out_fields = {
        f["typeName"]: f for f in out["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
    }
    assert out_fields["keyword"]["value"][0]["keywordValue"]["value"] == "group:Bo"
    kept = out_fields["datasetContact"]["value"][0]
    assert kept["datasetContactEmail"]["value"] == "real@example.org"
    assert kept["datasetContactName"]["value"] == "Real Person"
