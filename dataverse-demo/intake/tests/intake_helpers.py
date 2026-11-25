"""Shared fakes for the intake tests."""

from __future__ import annotations

import threading
from typing import Any

from intake_app.errors import PermanentError, TransientError
from intake_app.gema_runner import BuiltPayload
from intake_app.store import Store


def make_dataset_json() -> dict[str, Any]:
    """Shape of exporters/dataverse.py's output, trimmed to what the intake touches."""

    def prim(name: str, value: str) -> dict[str, Any]:
        return {"typeName": name, "multiple": False, "typeClass": "primitive", "value": value}

    return {
        "datasetVersion": {
            "metadataBlocks": {
                "citation": {
                    "fields": [
                        prim("title", "A dataset"),
                        {
                            "typeName": "datasetContact",
                            "multiple": True,
                            "typeClass": "compound",
                            "value": [
                                {
                                    "datasetContactName": prim("datasetContactName", "Unknown"),
                                    "datasetContactEmail": prim(
                                        "datasetContactEmail", "unknown@example.org"
                                    ),
                                }
                            ],
                        },
                        {
                            "typeName": "keyword",
                            "multiple": True,
                            "typeClass": "compound",
                            "value": [{"keywordValue": prim("keywordValue", "ocean")}],
                        },
                    ]
                }
            }
        }
    }


def add(store: Store, url: str, pseudonym: str = "ana", hints: str = "") -> int:
    return store.add(
        url=url, url_norm=url.lower(), hints=hints, pseudonym=pseudonym, max_records=1000
    ).id


class FakeBuilder:
    """Stands in for GemaRunner. URLs containing a marker misbehave on purpose."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.hints: dict[str, str] = {}
        self._flaky_seen: set[str] = set()
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.delay = 0.0

    def build_payload(self, url: str, hints: str) -> BuiltPayload:
        import time

        with self._lock:
            self.calls.append(url)
            self.hints[url] = hints
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            if "broken" in url:
                raise PermanentError("URL returned HTTP 404")
            if "boom" in url:
                raise RuntimeError("unexpected explosion")
            if "hang" in url:
                time.sleep(2)
            if "flaky" in url:
                with self._lock:
                    first = url not in self._flaky_seen
                    self._flaky_seen.add(url)
                if first:
                    raise TransientError("provider returned HTTP 503")
            return BuiltPayload(dataset_json=make_dataset_json())
        finally:
            with self._lock:
                self.active -= 1


class FakePublisher:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.published: list[str] = []
        self.fail_publish_for: set[str] = set()
        self._lock = threading.Lock()

    def create_dataset(self, payload: dict[str, Any]) -> str:
        with self._lock:
            self.created.append(payload)
            return f"perma:DV/T{len(self.created)}"

    def publish(self, pid: str) -> None:
        if pid in self.fail_publish_for:
            self.fail_publish_for.discard(pid)
            raise TransientError("publish dataset: Dataverse HTTP 503: unavailable")
        with self._lock:
            self.published.append(pid)

    def dataset_url(self, pid: str) -> str:
        return f"http://dv.test/dataset.xhtml?persistentId={pid}"
