"""Very light upload proxy: a form to paste/upload a Dataverse-native JSON
dataset payload, forwarded straight to a Dataverse instance's native API.

No auth of its own, no database, no session state — this exists to sit
behind a Tailscale-restricted host so attendees without API tooling can
still get a dataset into the demo instance. See ../README.md.
"""

from __future__ import annotations

import json
import os

import httpx
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

DATAVERSE_URL = os.environ.get("DATAVERSE_URL", "http://dataverse:8080")
API_TOKEN = os.environ.get("DATAVERSE_API_TOKEN", "")
DEFAULT_COLLECTION = os.environ.get("DATAVERSE_COLLECTION_ALIAS", "root")

app = FastAPI(title="Dataverse upload proxy")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


@app.get("/", response_class=HTMLResponse)
async def form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "upload.html",
        {"collection": DEFAULT_COLLECTION, "result": None, "error": None},
    )


@app.post("/upload", response_class=HTMLResponse)
async def upload(
    request: Request,
    collection: str = Form(default=DEFAULT_COLLECTION),
    publish: bool = Form(default=False),
    pasted_json: str = Form(default=""),
    file: UploadFile | None = None,
) -> HTMLResponse:
    if not API_TOKEN:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {
                "collection": collection,
                "result": None,
                "error": "Server has no DATAVERSE_API_TOKEN configured — set it in .env and "
                "recreate the uploader container.",
            },
        )

    raw = await file.read() if file is not None and file.filename else pasted_json.encode()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"collection": collection, "result": None, "error": f"Not valid JSON: {exc}"},
        )

    headers = {"X-Dataverse-key": API_TOKEN, "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{DATAVERSE_URL}/api/dataverses/{collection}/datasets",
                json=payload,
                headers=headers,
                timeout=30,
            )
        except httpx.RequestError as exc:
            return templates.TemplateResponse(
                request,
                "upload.html",
                {"collection": collection, "result": None, "error": f"Could not reach Dataverse: {exc}"},
            )

    body = resp.json()
    if resp.status_code >= 400:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"collection": collection, "result": None, "error": f"Dataverse rejected it ({resp.status_code}): {body}"},
        )

    persistent_id = body["data"]["persistentId"]
    publish_error = None
    if publish:
        async with httpx.AsyncClient() as client:
            pub_resp = await client.post(
                f"{DATAVERSE_URL}/api/datasets/:persistentId/actions/:publish",
                params={"persistentId": persistent_id, "type": "major"},
                headers=headers,
                timeout=30,
            )
        if pub_resp.status_code >= 400:
            publish_error = f"Created but publish failed ({pub_resp.status_code}): {pub_resp.json()}"

    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "collection": collection,
            "error": publish_error,
            "result": {
                "persistent_id": persistent_id,
                "url": f"{DATAVERSE_URL}/citation?persistentId={persistent_id}",
                "published": publish and not publish_error,
            },
        },
    )
