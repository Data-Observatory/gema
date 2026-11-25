from __future__ import annotations

import pytest
from intake_app.store import (
    DONE,
    FAILED,
    PENDING,
    PROCESSING,
    DuplicateError,
    LimitReachedError,
    Store,
)
from intake_app.urls import normalize_url
from intake_helpers import add


def _add(store: Store, url: str, pseudonym: str = "ana", max_records: int = 40) -> int:
    return store.add(
        url=url,
        url_norm=normalize_url(url),
        hints="",
        pseudonym=pseudonym,
        max_records=max_records,
    ).id


def test_add_starts_pending_and_persists(store: Store, tmp_path) -> None:
    rid = _add(store, "https://a.org/x")
    rec = store.get(rid)
    assert rec is not None
    assert (rec.status, rec.pseudonym, rec.error, rec.dataverse_pid) == (PENDING, "ana", "", "")
    # a fresh Store on the same file sees it (survives restarts)
    reopened = Store(tmp_path / "intake.db")
    reopened.init()
    assert [r.id for r in reopened.all_records()] == [rid]


def test_duplicate_is_rejected_naming_the_first_submitter(store: Store) -> None:
    _add(store, "https://a.org/x", pseudonym="ana")
    for variant in ("https://A.org/x/", "https://a.org/x#frag", "https://a.org/x"):
        with pytest.raises(DuplicateError) as exc:
            _add(store, variant, pseudonym="bob")
        assert exc.value.pseudonym == "ana"
    assert len(store.all_records()) == 1


def test_record_limit(store: Store) -> None:
    _add(store, "https://a.org/1", max_records=2)
    _add(store, "https://a.org/2", max_records=2)
    with pytest.raises(LimitReachedError):
        _add(store, "https://a.org/3", max_records=2)


def test_delete_only_while_pending_or_failed(store: Store) -> None:
    pending = add(store, "https://a.org/p")
    failed = add(store, "https://a.org/f")
    processing = add(store, "https://a.org/r")
    done = add(store, "https://a.org/d")
    for rid, status in ((failed, FAILED), (processing, PROCESSING), (done, DONE)):
        assert store.claim(rid, PENDING) is not None
        if status == FAILED:
            store.mark_failed(rid, "x")
        elif status == DONE:
            store.mark_done(rid)

    assert store.delete(processing) is False
    assert store.delete(done) is False
    assert store.delete(pending) is True
    assert store.delete(failed) is True
    assert store.delete(pending) is False  # already gone
    assert {r.id for r in store.all_records()} == {processing, done}


def test_status_transitions(store: Store) -> None:
    rid = add(store, "https://a.org/x")
    assert store.get(rid).status == PENDING  # type: ignore[union-attr]

    claimed = store.claim(rid, PENDING)
    assert claimed is not None and claimed.status == PROCESSING
    assert store.claim(rid, PENDING) is None  # cannot be claimed twice

    assert store.mark_failed(rid, "URL returned HTTP 404") is True
    rec = store.get(rid)
    assert rec is not None and (rec.status, rec.error) == (FAILED, "URL returned HTTP 404")
    assert store.claim(rid, PENDING) is None  # Process never touches failed...
    claimed = store.claim(rid, FAILED)  # ...Retry failed does, and clears the error
    assert claimed is not None and (claimed.status, claimed.error) == (PROCESSING, "")

    assert store.mark_done(rid) is True
    assert store.get(rid).status == DONE  # type: ignore[union-attr]
    # done is terminal: nothing can claim it or flip it back
    assert store.claim(rid, PENDING) is None
    assert store.claim(rid, FAILED) is None
    assert store.mark_failed(rid, "late") is False
    assert store.get(rid).status == DONE  # type: ignore[union-attr]


def test_finish_requires_processing(store: Store) -> None:
    rid = add(store, "https://a.org/x")
    assert store.mark_done(rid) is False  # still pending
    assert store.get(rid).status == PENDING  # type: ignore[union-attr]


def test_set_pid_is_kept_across_failure(store: Store) -> None:
    rid = add(store, "https://a.org/x")
    store.claim(rid, PENDING)
    store.set_pid(rid, "perma:DV/AAA", "http://dv/dataset.xhtml?persistentId=perma:DV/AAA")
    store.mark_failed(rid, "publish failed")
    rec = store.get(rid)
    assert rec is not None and rec.dataverse_pid == "perma:DV/AAA" and rec.status == FAILED


def test_recover_stale_processing_rows(store: Store) -> None:
    stuck = add(store, "https://a.org/stuck")
    done = add(store, "https://a.org/done")
    store.claim(stuck, PENDING)
    store.claim(done, PENDING)
    store.mark_done(done)
    assert store.recover_stale() == 1
    assert store.get(stuck).status == PENDING  # type: ignore[union-attr]
    assert store.get(done).status == DONE  # type: ignore[union-attr]
    assert store.recover_stale() == 0


def test_counts_and_ids(store: Store) -> None:
    a, b, c = (add(store, f"https://a.org/{i}") for i in range(3))
    store.claim(b, PENDING)
    store.mark_done(b)
    store.claim(c, PENDING)
    store.mark_failed(c, "e")
    assert store.counts() == {PENDING: 1, PROCESSING: 0, DONE: 1, FAILED: 1}
    assert store.ids_with_status(PENDING) == [a]


def test_intake_open_flag_defaults_open_and_persists(store: Store, tmp_path) -> None:
    assert store.is_open() is True
    store.set_open(False)
    assert store.is_open() is False
    other = Store(tmp_path / "intake.db")
    assert other.is_open() is False
    store.set_open(True)
    assert store.is_open() is True


def test_sql_is_parameterized(store: Store) -> None:
    nasty = "x'); DROP TABLE resources;--"
    _add(store, "https://a.org/ok", pseudonym=nasty)
    assert store.all_records()[0].pseudonym == nasty
