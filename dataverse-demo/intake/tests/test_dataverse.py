from __future__ import annotations

from typing import Any

import httpx
import pytest
from intake_app.dataverse import DataverseClient
from intake_app.errors import PermanentError, TransientError


class Recorder:
    """Replaces httpx.request: scripted responses, records every call."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def response(status: int, body: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body if body is not None else {})


@pytest.fixture
def client() -> DataverseClient:
    return DataverseClient(
        base_url="http://dataverse:8080",
        public_url="http://localhost:8080/",
        token="secret-token",
        collection_alias="gema-demo",
    )


def test_create_dataset_posts_to_collection_and_returns_pid(
    client: DataverseClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = Recorder(response(201, {"status": "OK", "data": {"persistentId": "perma:DV/ABC"}}))
    monkeypatch.setattr(httpx, "request", rec)
    assert client.create_dataset({"a": 1}) == "perma:DV/ABC"
    call = rec.calls[0]
    assert call["url"] == "http://dataverse:8080/api/dataverses/gema-demo/datasets"
    assert call["headers"] == {"X-Dataverse-key": "secret-token"}
    assert call["json"] == {"a": 1}


def test_publish_skips_an_already_released_dataset(
    client: DataverseClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = Recorder(response(200, {"data": {"latestVersion": {"versionState": "RELEASED"}}}))
    monkeypatch.setattr(httpx, "request", rec)
    client.publish("perma:DV/ABC")
    assert [c["method"] for c in rec.calls] == ["GET"]  # no POST: nothing to publish


def test_publish_draft_posts_publish_action(
    client: DataverseClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = Recorder(
        response(200, {"data": {"latestVersion": {"versionState": "DRAFT"}}}),
        response(200, {"status": "OK"}),
    )
    monkeypatch.setattr(httpx, "request", rec)
    client.publish("perma:DV/ABC")
    post = rec.calls[1]
    assert post["method"] == "POST"
    assert post["url"].endswith("/api/datasets/:persistentId/actions/:publish")
    assert post["params"] == {"persistentId": "perma:DV/ABC", "type": "major"}


@pytest.mark.parametrize("status", [500, 502, 503, 429])
def test_server_errors_and_rate_limits_are_transient(
    client: DataverseClient, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setattr(httpx, "request", Recorder(response(status, {"message": "nope"})))
    with pytest.raises(TransientError):
        client.create_dataset({})


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_are_permanent_with_dataverse_message(
    client: DataverseClient, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setattr(httpx, "request", Recorder(response(status, {"message": "bad field"})))
    with pytest.raises(PermanentError, match="bad field"):
        client.create_dataset({})


def test_network_error_is_transient_and_never_leaks_the_token(
    client: DataverseClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(httpx, "request", Recorder(httpx.ConnectError("refused")))
    with pytest.raises(TransientError) as exc:
        client.create_dataset({})
    assert "secret-token" not in str(exc.value)


def test_missing_token_is_a_clear_permanent_error() -> None:
    bare = DataverseClient(
        base_url="http://x", public_url="http://x", token="", collection_alias="root"
    )
    with pytest.raises(PermanentError, match="DATAVERSE_API_TOKEN"):
        bare.create_dataset({})


def test_dataset_url_uses_the_public_address(client: DataverseClient) -> None:
    assert (
        client.dataset_url("perma:DV/ABC")
        == "http://localhost:8080/dataset.xhtml?persistentId=perma:DV/ABC"
    )
