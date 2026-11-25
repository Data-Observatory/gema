"""Dataverse native-API side: payload finishing, create dataset, publish."""

from __future__ import annotations

import copy
import logging
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from intake_app.errors import PermanentError, TransientError

logger = logging.getLogger(__name__)

# What gema's exporter writes when the source metadata has no contact e-mail at all.
EXPORTER_PLACEHOLDER_EMAIL = "unknown@example.org"
EXPORTER_PLACEHOLDER_NAME = "Unknown"


class Publisher(Protocol):
    def create_dataset(self, payload: dict[str, Any]) -> str:
        """Create a draft dataset, return its persistent id."""

    def publish(self, pid: str) -> None:
        """Publish *pid*. Must be a no-op if it is already published."""

    def dataset_url(self, pid: str) -> str:
        """Browser-reachable link to the dataset page."""


def _primitive(type_name: str, value: str) -> dict[str, Any]:
    return {"typeName": type_name, "multiple": False, "typeClass": "primitive", "value": value}


def finalize_payload(
    dataset_json: dict[str, Any],
    *,
    pseudonym: str,
    default_contact_email: str,
    default_contact_name: str,
) -> dict[str, Any]:
    """Return a copy of the exporter's payload with the intake-specific bits filled in.

    * the attendee's pseudonym becomes the keyword ``group:<pseudonym>`` (never an author,
      publisher or depositor-like field: it describes who submitted, not who made the data);
    * the exporter's "no contact found" placeholders are swapped for the configured default
      contact, since Dataverse requires one.
    """
    payload = copy.deepcopy(dataset_json)
    fields: list[dict[str, Any]] = payload["datasetVersion"]["metadataBlocks"]["citation"]["fields"]

    group_entry = {"keywordValue": _primitive("keywordValue", f"group:{pseudonym}")}
    keyword_field = next((f for f in fields if f.get("typeName") == "keyword"), None)
    if keyword_field is None:
        fields.append(
            {
                "typeName": "keyword",
                "multiple": True,
                "typeClass": "compound",
                "value": [group_entry],
            }
        )
    else:
        keyword_field["value"].append(group_entry)

    contact_field = next((f for f in fields if f.get("typeName") == "datasetContact"), None)
    if contact_field is not None:
        for entry in contact_field["value"]:
            email = entry.get("datasetContactEmail")
            if email and email.get("value") == EXPORTER_PLACEHOLDER_EMAIL:
                email["value"] = default_contact_email
                name = entry.get("datasetContactName")
                if name and name.get("value") == EXPORTER_PLACEHOLDER_NAME:
                    name["value"] = default_contact_name
    return payload


def _api_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        message = body.get("message") if isinstance(body, dict) else None
    except ValueError:
        message = None
    return str(message or resp.text or "")[:200].replace("\n", " ")


def _raise_for_status(resp: httpx.Response, what: str) -> None:
    if resp.status_code < 400:
        return
    detail = f"{what}: Dataverse HTTP {resp.status_code}: {_api_message(resp)}"
    if resp.status_code >= 500 or resp.status_code == 429:
        raise TransientError(detail)
    raise PermanentError(detail)


class DataverseClient:
    def __init__(
        self,
        *,
        base_url: str,
        public_url: str,
        token: str,
        collection_alias: str,
        timeout: float = 30,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._public = public_url.rstrip("/")
        self._token = token
        self._alias = collection_alias
        self._timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self._token:
            raise PermanentError("DATAVERSE_API_TOKEN is not configured")
        try:
            return httpx.request(
                method,
                f"{self._base}{path}",
                headers={"X-Dataverse-key": self._token},
                timeout=self._timeout,
                **kwargs,
            )
        except httpx.TransportError as exc:
            raise TransientError(f"cannot reach Dataverse: {type(exc).__name__}") from exc

    def create_dataset(self, payload: dict[str, Any]) -> str:
        resp = self._request(
            "POST", f"/api/dataverses/{quote(self._alias, safe='')}/datasets", json=payload
        )
        _raise_for_status(resp, "create dataset")
        try:
            pid = str(resp.json()["data"]["persistentId"])
        except (ValueError, KeyError, TypeError):
            raise PermanentError("create dataset: unexpected Dataverse response") from None
        logger.info("dataverse: created dataset %s", pid)
        return pid

    def _is_released(self, pid: str) -> bool:
        resp = self._request("GET", "/api/datasets/:persistentId/", params={"persistentId": pid})
        _raise_for_status(resp, "read dataset")
        try:
            state = resp.json()["data"]["latestVersion"]["versionState"]
        except (ValueError, KeyError, TypeError):
            return False
        return bool(state == "RELEASED")

    def publish(self, pid: str) -> None:
        if self._is_released(pid):
            logger.info("dataverse: %s already published", pid)
            return
        resp = self._request(
            "POST",
            "/api/datasets/:persistentId/actions/:publish",
            params={"persistentId": pid, "type": "major"},
        )
        _raise_for_status(resp, "publish dataset")
        logger.info("dataverse: published %s", pid)

    def dataset_url(self, pid: str) -> str:
        return f"{self._public}/dataset.xhtml?persistentId={quote(pid, safe=':/')}"
