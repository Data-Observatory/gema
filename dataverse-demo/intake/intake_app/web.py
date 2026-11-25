"""The HTTP layer: public page at ``/`` and admin at ``/admin/``.

Served behind Caddy's ``handle_path /intake/*`` (prefix stripped), so every link, form
action, fetch and redirect here is *relative* and works under any prefix -- or none.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from intake_app.config import Settings
from intake_app.processor import BatchProcessor
from intake_app.ratelimit import RateLimiter
from intake_app.store import FAILED, PENDING, DuplicateError, LimitReachedError, Store
from intake_app.urls import InvalidUrlError, is_forbidden_literal, normalize_url

logger = logging.getLogger(__name__)

MAX_HINTS = 1000
MAX_PSEUDONYM = 50
COOKIE = "intake_admin"
# Control characters (newlines would forge lines in intake.log, where the processor logs the
# pseudonym) and bidi overrides (would visually reorder the admin/public lists).
_PSEUDONYM_BAD_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")

_REFRESH_JS = """\
(function () {
  var box = document.getElementById("live");
  if (!box) { return; }
  var url = box.getAttribute("data-src");
  function tick() {
    fetch(url, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) { if (html !== null) { box.innerHTML = html; } })
      .catch(function () {});
  }
  setInterval(tick, 10000);
})();
"""

_FLASH = {
    "added": "Resource added. Thank you!",
    "deleted": "Deleted.",
    "not_deletable": "Only pending or failed records can be deleted.",
    "opened": "Intake is open.",
    "closed": "Intake is closed.",
    "started": "Processing started.",
    "retrying": "Retrying failed records.",
    "nothing": "Nothing to process.",
    "busy": "A batch is already running.",
    "no_token": "DATAVERSE_API_TOKEN is not configured; cannot publish.",
    "bad_login": "Wrong token.",
    "rate": "Too many attempts, wait a minute.",
}

_CSV_COLUMNS = (
    "id", "pseudonym", "url", "hints", "status", "error", "dataverse_pid", "dataverse_url",
    "created_at", "updated_at",
)  # fmt: skip


def _digest(token: str, purpose: str) -> str:
    return hmac.new(token.encode(), f"gema-intake:{purpose}".encode(), hashlib.sha256).hexdigest()


def _safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _csv_cell(value: object) -> str:
    text = str(value)
    # Neutralize spreadsheet formula injection from attendee-supplied text.
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def client_ip(request: Request) -> str:
    """Caddy sets X-Real-IP from its own client_ip (overwriting anything client-sent), so it
    is the first choice; else the rightmost X-Forwarded-For entry (the one the nearest proxy
    appended, the only one a client cannot forge); else the socket peer."""
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def create_app(
    settings: Settings, store: Store, processor: BatchProcessor, *, can_publish: bool = True
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        # uvicorn runs this on SIGTERM/SIGINT (docker stop / compose restart): stop claiming,
        # give in-flight records a grace period, put interrupted ones back to pending.
        await asyncio.to_thread(processor.shutdown, settings.shutdown_grace)

    app = FastAPI(
        lifespan=lifespan,
        title="GEMA! workshop intake",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    submit_limiter = RateLimiter(settings.rate_limit, settings.rate_window)
    login_limiter = RateLimiter(10, 60)
    session_value = _digest(settings.admin_token, "session")
    csrf_value = _digest(settings.admin_token, "csrf")

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
            "connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    def render(request: Request, name: str, status_code: int = 200, **ctx: object) -> HTMLResponse:
        base = {
            "records": store.all_records(),
            "counts": store.counts(),
            "intake_open": store.is_open(),
            "max_records": settings.max_records,
            "hints_max": MAX_HINTS,
            "pseudonym_max": MAX_PSEUDONYM,
            "flash": "",
            "error": "",
            "form": {"url": "", "hints": "", "pseudonym": ""},
            "running": processor.is_running(),
            "csrf": csrf_value,
        }
        base.update(ctx)
        return templates.TemplateResponse(request, name, base, status_code=status_code)

    def flash_redirect(target: str, key: str) -> RedirectResponse:
        return RedirectResponse(f"{target}?m={key}", status_code=303)

    def flash_from(request: Request) -> str:
        return _FLASH.get(request.query_params.get("m", ""), "")

    # -- public --------------------------------------------------------------------------

    @app.get("/refresh.js")
    def refresh_js() -> PlainTextResponse:
        return PlainTextResponse(_REFRESH_JS, media_type="text/javascript")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return render(request, "index.html", flash=flash_from(request))

    @app.get("/list", response_class=HTMLResponse)
    def public_list(request: Request) -> HTMLResponse:
        return render(request, "_public_list.html")

    @app.post("/submit", response_class=HTMLResponse)
    def submit(
        request: Request,
        url: str = Form(default=""),
        hints: str = Form(default=""),
        pseudonym: str = Form(default=""),
    ) -> Response:
        form = {"url": url.strip(), "hints": hints.strip(), "pseudonym": pseudonym.strip()}

        def reject(message: str, status: int) -> HTMLResponse:
            return render(request, "index.html", status_code=status, error=message, form=form)

        if not store.is_open():
            return reject("Submissions closed.", 403)
        if not form["pseudonym"]:
            return reject("Pseudonym is required.", 400)
        if len(form["pseudonym"]) > MAX_PSEUDONYM:
            return reject(f"Pseudonym is too long (max {MAX_PSEUDONYM} characters).", 400)
        if _PSEUDONYM_BAD_RE.search(form["pseudonym"]):
            return reject("Pseudonym must not contain line breaks or control characters.", 400)
        if len(form["hints"]) > MAX_HINTS:
            return reject(f"Hints are too long (max {MAX_HINTS} characters).", 400)
        try:
            url_norm = normalize_url(form["url"])
        except InvalidUrlError as exc:
            return reject(str(exc), 400)
        if not settings.allow_private_urls and is_forbidden_literal(url_norm):
            return reject("That address is not publicly reachable.", 400)
        # Counted only once the form is valid: at a workshop many attendees share one venue
        # IP (NAT), so a typo or a blank field must not eat the room's submission budget.
        if not submit_limiter.allow(client_ip(request)):
            return reject("Too many submissions from your address; please wait a minute.", 429)
        try:
            store.add(
                url=form["url"],
                url_norm=url_norm,
                hints=form["hints"],
                pseudonym=form["pseudonym"],
                max_records=settings.max_records,
            )
        except DuplicateError as exc:
            return reject(f"This URL was already submitted by “{exc.pseudonym}”.", 409)
        except LimitReachedError:
            return reject("The resource limit has been reached; no more submissions.", 409)
        logger.info("submitted by %r from %s: %s", form["pseudonym"], client_ip(request), url_norm)
        return flash_redirect("./", "added")

    # -- admin ---------------------------------------------------------------------------

    def is_admin(request: Request) -> bool:
        return _safe_equal(request.cookies.get(COOKIE, ""), session_value)

    def csrf_ok(request: Request, token: str) -> bool:
        return is_admin(request) and _safe_equal(token, csrf_value)

    def denied(target: str = "./") -> RedirectResponse:
        # *target* is relative to the POST URL: "./" from /admin/<action>, "../" from
        # /admin/delete/<id> (where "./" would land on the non-existent /admin/delete/).
        return RedirectResponse(target, status_code=303)

    @app.get("/admin")
    def admin_no_slash() -> RedirectResponse:
        # Relative on purpose: from /intake/admin this resolves to /intake/admin/.
        return RedirectResponse("admin/", status_code=308)

    @app.get("/admin/", response_class=HTMLResponse)
    def admin_home(request: Request) -> HTMLResponse:
        if not is_admin(request):
            return render(request, "admin_login.html", flash=flash_from(request))
        return render(request, "admin.html", flash=flash_from(request))

    @app.get("/admin/list", response_class=HTMLResponse)
    def admin_list(request: Request) -> Response:
        if not is_admin(request):
            return Response(status_code=401)
        return render(request, "_admin_list.html")

    @app.post("/admin/login")
    def admin_login(request: Request, token: str = Form(default="")) -> Response:
        if not login_limiter.allow(client_ip(request)):
            return flash_redirect("./", "rate")
        if not _safe_equal(_digest(token, "login"), _digest(settings.admin_token, "login")):
            logger.warning("admin login failed from %s", client_ip(request))
            return flash_redirect("./", "bad_login")
        response = RedirectResponse("./", status_code=303)
        prefix = request.headers.get("x-forwarded-prefix", "").rstrip("/")
        response.set_cookie(
            COOKIE,
            session_value,
            path=f"{prefix}/admin/",
            httponly=True,
            samesite="strict",
            secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
            max_age=12 * 3600,
        )
        logger.info("admin login from %s", client_ip(request))
        return response

    @app.post("/admin/logout")
    def admin_logout(request: Request, csrf: str = Form(default="")) -> Response:
        response = RedirectResponse("./", status_code=303)
        if csrf_ok(request, csrf):
            prefix = request.headers.get("x-forwarded-prefix", "").rstrip("/")
            response.delete_cookie(COOKIE, path=f"{prefix}/admin/")
        return response

    @app.post("/admin/delete/{rid}")
    def admin_delete(request: Request, rid: int, csrf: str = Form(default="")) -> Response:
        if not csrf_ok(request, csrf):
            return denied("../")
        deleted = store.delete(rid)
        logger.info("admin delete %s: %s", rid, "ok" if deleted else "refused")
        # POST /admin/delete/<id>: ".." resolves to /admin/ (relative, prefix-safe).
        return flash_redirect("../", "deleted" if deleted else "not_deletable")

    @app.post("/admin/toggle")
    def admin_toggle(request: Request, csrf: str = Form(default="")) -> Response:
        if not csrf_ok(request, csrf):
            return denied()
        now_open = not store.is_open()
        store.set_open(now_open)
        logger.info("admin: intake %s", "opened" if now_open else "closed")
        return flash_redirect("./", "opened" if now_open else "closed")

    def start_batch(request: Request, csrf: str, from_status: str, started_key: str) -> Response:
        if not csrf_ok(request, csrf):
            return denied()
        if not can_publish:
            return flash_redirect("./", "no_token")
        queued = processor.start(from_status)
        if queued is None:
            return flash_redirect("./", "busy")
        logger.info("admin: batch from %r, %d queued", from_status, queued)
        return flash_redirect("./", started_key if queued else "nothing")

    @app.post("/admin/process")
    def admin_process(request: Request, csrf: str = Form(default="")) -> Response:
        return start_batch(request, csrf, PENDING, "started")

    @app.post("/admin/retry")
    def admin_retry(request: Request, csrf: str = Form(default="")) -> Response:
        return start_batch(request, csrf, FAILED, "retrying")

    @app.get("/admin/export.csv")
    def admin_export(request: Request) -> Response:
        if not is_admin(request):
            return Response(status_code=401)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(_CSV_COLUMNS)
        for record in reversed(store.all_records()):
            writer.writerow([_csv_cell(getattr(record, col)) for col in _CSV_COLUMNS])
        return Response(
            buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="intake-results.csv"'},
        )

    return app
