from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("multipart")
pytest.importorskip("jinja2")

from fastapi.testclient import TestClient  # noqa: E402
from intake_app.config import Settings  # noqa: E402
from intake_app.processor import BatchProcessor, Defaults  # noqa: E402
from intake_app.store import DONE, FAILED, Store  # noqa: E402
from intake_app.web import create_app  # noqa: E402
from intake_helpers import FakeBuilder, FakePublisher, add  # noqa: E402

TOKEN = "s3cret-admin-token"


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "admin_token": TOKEN,
        "data_dir": tmp_path,
        "log_file": tmp_path / "intake.log",
        "dataverse_url": "http://dv",
        "dataverse_public_url": "http://dv",
        "dataverse_token": "t",
        "collection_alias": "root",
        "default_contact_email": "c@example.test",
        "default_contact_name": "W",
        "gema_config": tmp_path / "a.yaml",
        "export_config": tmp_path / "b.yaml",
        "opencode_api_key": "k",
        "rate_limit": 100,
        "max_records": 40,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class Env:
    def __init__(self, tmp_path: Path, **overrides: object) -> None:
        self.settings = make_settings(tmp_path, **overrides)
        self.store = Store(self.settings.db_path)
        self.store.init()
        self.builder = FakeBuilder()
        self.publisher = FakePublisher()
        self.processor = BatchProcessor(
            self.store,
            self.builder,
            self.publisher,
            Defaults("c@example.test", "W"),
            workers=4,
            record_timeout=30,
            retry_delay=0,
            sleep=lambda _s: None,
        )
        self.app = create_app(self.settings, self.store, self.processor)
        self.client = TestClient(self.app, follow_redirects=False)

    def login(self) -> str:
        r = self.client.post("/admin/login", data={"token": TOKEN})
        assert r.status_code == 303
        page = self.client.get("/admin/").text
        match = re.search(r'name="csrf" value="([0-9a-f]+)"', page)
        assert match
        return match.group(1)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def submit(
    env: Env, url: str = "https://ok.org/x", pseudonym: str = "Ana", hints: str = "", **kw: str
):  # type: ignore[no-untyped-def]
    return env.client.post(
        "/submit", data={"url": url, "hints": hints, "pseudonym": pseudonym}, headers=kw
    )


# -- public page ----------------------------------------------------------------------------


def test_public_page_is_mobile_friendly_and_has_no_admin_actions(env: Env) -> None:
    html = env.client.get("/").text
    assert 'name="viewport"' in html
    assert 'action="submit"' in html
    assert "admin" not in html.lower().replace("administrator", "")
    assert "Delete" not in html and "Process" not in html


def test_submit_adds_resource_and_redirects_relative(env: Env) -> None:
    r = submit(env, hints="my hint", pseudonym="Ana")
    assert r.status_code == 303 and r.headers["location"].startswith("./")  # prefix-safe
    html = env.client.get("/list").text
    assert "https://ok.org/x" in html and "Ana" in html and "my hint" in html
    assert "pending" in html


def test_duplicate_is_rejected_naming_the_first_pseudonym(env: Env) -> None:
    assert submit(env, "https://ok.org/x", "Ana").status_code == 303
    r = submit(env, "https://OK.org/x/#frag", "Bob")
    assert r.status_code == 409
    assert "already submitted by" in r.text and "Ana" in r.text
    assert len(env.store.all_records()) == 1


@pytest.mark.parametrize(
    ("data", "needle"),
    [
        ({"url": "", "pseudonym": "a"}, "URL is required"),
        ({"url": "ftp://x.org/a", "pseudonym": "a"}, "http"),
        ({"url": "https://ok.org/x", "pseudonym": ""}, "Pseudonym is required"),
        ({"url": "https://ok.org/x", "pseudonym": "p" * 51}, "Pseudonym is too long"),
        ({"url": "https://ok.org/x", "pseudonym": "a", "hints": "h" * 1001}, "too long"),
        ({"url": "http://localhost:8080/", "pseudonym": "a"}, "not publicly reachable"),
        ({"url": "http://169.254.169.254/", "pseudonym": "a"}, "not publicly reachable"),
    ],
)
def test_validation_rejections(env: Env, data: dict[str, str], needle: str) -> None:
    r = env.client.post("/submit", data=data)
    assert r.status_code == 400 and needle in r.text
    assert env.store.all_records() == []


def test_limits_accept_exact_maximums(env: Env) -> None:
    r = submit(env, pseudonym="p" * 50, hints="h" * 1000)
    assert r.status_code == 303


def test_form_values_survive_a_rejection_and_are_escaped(env: Env) -> None:
    r = env.client.post(
        "/submit",
        data={"url": "https://ok.org/x", "pseudonym": '"><script>alert(1)</script>' + "x" * 60},
    )
    assert r.status_code == 400
    assert "<script>alert(1)" not in r.text
    assert "&lt;script&gt;" in r.text


def test_user_content_is_html_escaped_everywhere(env: Env) -> None:
    evil = "<img src=x onerror=alert(1)>"
    assert submit(env, "https://ok.org/x?q=<b>", evil, evil).status_code == 303
    login = env.login()
    for page in (
        env.client.get("/").text,
        env.client.get("/list").text,
        env.client.get("/admin/").text,
        env.client.get("/admin/list").text,
    ):
        assert "<img src=x" not in page and "<b>" not in page
        assert "&lt;img" in page
    assert login


def test_closed_intake_disables_form_and_rejects_posts(env: Env) -> None:
    csrf = env.login()
    env.client.post("/admin/toggle", data={"csrf": csrf})
    assert env.store.is_open() is False
    page = env.client.get("/").text
    assert "Submissions closed" in page and "<fieldset disabled>" in page
    assert 'action="submit"' not in page
    r = submit(env)
    assert r.status_code == 403 and "Submissions closed" in r.text
    assert env.store.all_records() == []
    env.client.post("/admin/toggle", data={"csrf": csrf})
    assert submit(env).status_code == 303


def test_max_records_cap(tmp_path: Path) -> None:
    env = Env(tmp_path, max_records=2)
    assert submit(env, "https://ok.org/1").status_code == 303
    assert submit(env, "https://ok.org/2").status_code == 303
    r = submit(env, "https://ok.org/3")
    assert r.status_code == 409 and "limit" in r.text.lower()


def test_per_ip_rate_limit_honours_forwarded_ip(tmp_path: Path) -> None:
    env = Env(tmp_path, rate_limit=2)
    for i in range(2):
        assert submit(env, f"https://ok.org/{i}", **{"X-Real-IP": "9.9.9.9"}).status_code == 303
    assert submit(env, "https://ok.org/9", **{"X-Real-IP": "9.9.9.9"}).status_code == 429
    # a different visitor behind the same proxy is unaffected
    assert submit(env, "https://ok.org/10", **{"X-Real-IP": "8.8.8.8"}).status_code == 303
    # X-Forwarded-For: only the rightmost (proxy-appended) entry counts, not a forged one
    r = submit(env, "https://ok.org/11", **{"X-Forwarded-For": "1.2.3.4, 9.9.9.9"})
    assert r.status_code == 429


def test_public_list_shows_dataverse_link_only_when_done(env: Env) -> None:
    done = add(env.store, "https://ok.org/done", "Ana")
    add(env.store, "https://ok.org/pending", "Bob")
    env.store.claim(done, "pending")
    env.store.set_pid(done, "perma:DV/X", "http://dv/dataset.xhtml?persistentId=perma:DV/X")
    env.store.mark_done(done)
    html = env.client.get("/list").text
    assert html.count("View in Dataverse") == 1
    assert "http://dv/dataset.xhtml?persistentId=perma:DV/X" in html


def test_security_headers(env: Env) -> None:
    r = env.client.get("/")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


# -- admin ----------------------------------------------------------------------------------


def test_admin_requires_the_token(env: Env) -> None:
    assert "Admin token" in env.client.get("/admin/").text  # login form, no actions
    assert "Process" not in env.client.get("/admin/").text
    assert env.client.get("/admin/list").status_code == 401
    assert env.client.get("/admin/export.csv").status_code == 401
    r = env.client.post("/admin/login", data={"token": "wrong"})
    assert r.status_code == 303 and "bad_login" in r.headers["location"]
    assert "intake_admin" not in r.headers.get("set-cookie", "")


def test_admin_posts_need_cookie_and_csrf(env: Env) -> None:
    rid = add(env.store, "https://ok.org/x")
    # no session at all
    r = env.client.post(f"/admin/delete/{rid}", data={"csrf": "x"})
    assert r.status_code == 303 and env.store.get(rid) is not None
    csrf = env.login()
    # session but missing/wrong csrf
    assert env.client.post(f"/admin/delete/{rid}", data={}).status_code == 303
    assert env.client.post(f"/admin/delete/{rid}", data={"csrf": "nope"}).status_code == 303
    assert env.store.get(rid) is not None
    env.client.post(f"/admin/delete/{rid}", data={"csrf": csrf})
    assert env.store.get(rid) is None


def test_login_cookie_is_scoped_and_hardened(env: Env) -> None:
    r = env.client.post(
        "/admin/login",
        data={"token": TOKEN},
        headers={"X-Forwarded-Prefix": "/intake", "X-Forwarded-Proto": "https"},
    )
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
    assert "path=/intake/admin/" in cookie
    assert TOKEN not in r.headers["set-cookie"]  # only a derived value is stored


def test_admin_delete_rules_and_redirect_is_relative(env: Env) -> None:
    pending = add(env.store, "https://ok.org/p")
    done = add(env.store, "https://ok.org/d")
    env.store.claim(done, "pending")
    env.store.mark_done(done)
    csrf = env.login()
    r = env.client.post(f"/admin/delete/{done}", data={"csrf": csrf})
    assert "not_deletable" in r.headers["location"] and env.store.get(done) is not None
    r = env.client.post(f"/admin/delete/{pending}", data={"csrf": csrf})
    assert r.headers["location"].startswith("../") and env.store.get(pending) is None
    assert 'action="delete/' not in env.client.get("/admin/").text.replace(
        str(done), ""
    )  # no button for done


def test_admin_login_attempts_are_rate_limited(env: Env) -> None:
    for _ in range(10):
        env.client.post("/admin/login", data={"token": "bad"})
    r = env.client.post("/admin/login", data={"token": TOKEN})
    assert "rate" in r.headers["location"]


def test_admin_no_slash_redirects_relative(env: Env) -> None:
    r = env.client.get("/admin")
    assert r.status_code == 308 and r.headers["location"] == "admin/"


def test_full_workshop_flow_broken_url_fails_rest_publish(env: Env) -> None:
    for i in range(15):
        assert submit(env, f"https://ok.org/{i}", f"user{i}", f"hint {i}").status_code == 303
    assert submit(env, "https://broken.org/404", "zoe").status_code == 303
    csrf = env.login()

    r = env.client.post("/admin/process", data={"csrf": csrf})
    assert "started" in r.headers["location"]
    env.processor.wait(30)

    counts = env.store.counts()
    assert counts == {"pending": 0, "processing": 0, "done": 15, "failed": 1}
    admin_html = env.client.get("/admin/list").text
    assert "URL returned HTTP 404" in admin_html  # failure reason visible to admin
    assert "done 15" in admin_html and "failed 1" in admin_html
    public_html = env.client.get("/list").text
    assert public_html.count("View in Dataverse") == 15
    assert "URL returned HTTP 404" not in public_html  # internals stay off the public page
    assert env.builder.hints["https://ok.org/3"] == "hint 3"

    # Retry failed re-runs only the failed one; nothing else is re-uploaded.
    created_before = len(env.publisher.created)
    r = env.client.post("/admin/retry", data={"csrf": csrf})
    assert "retrying" in r.headers["location"]
    env.processor.wait(30)
    assert len(env.publisher.created) == created_before
    failed = [x for x in env.store.all_records() if x.status == FAILED]
    assert len(failed) == 1 and sum(x.status == DONE for x in env.store.all_records()) == 15


def test_process_with_nothing_pending_and_busy_messages(env: Env) -> None:
    csrf = env.login()
    r = env.client.post("/admin/process", data={"csrf": csrf})
    assert "nothing" in r.headers["location"]
    add(env.store, "https://ok.org/x")
    env.builder.delay = 0.3
    env.client.post("/admin/process", data={"csrf": csrf})
    r = env.client.post("/admin/retry", data={"csrf": csrf})
    assert "busy" in r.headers["location"]
    env.processor.wait(30)


def test_process_refused_without_dataverse_token(tmp_path: Path) -> None:
    env = Env(tmp_path)
    app = create_app(env.settings, env.store, env.processor, can_publish=False)
    client = TestClient(app, follow_redirects=False)
    client.post("/admin/login", data={"token": TOKEN})
    csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', client.get("/admin/").text).group(1)  # type: ignore[union-attr]
    add(env.store, "https://ok.org/x")
    r = client.post("/admin/process", data={"csrf": csrf})
    assert "no_token" in r.headers["location"]
    assert env.store.counts()["pending"] == 1


def test_csv_export_has_results_and_neutralizes_formulas(env: Env) -> None:
    add(env.store, "https://ok.org/a", '=HYPERLINK("http://evil")', "+cmd")
    rid = add(env.store, "https://broken.org/b", "Bob")
    csrf = env.login()
    env.client.post("/admin/process", data={"csrf": csrf})
    env.processor.wait(30)
    r = env.client.get("/admin/export.csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 2
    by_url = {row["url"]: row for row in rows}
    ok = by_url["https://ok.org/a"]
    assert ok["status"] == "done" and ok["dataverse_pid"].startswith("perma:DV/")
    assert ok["pseudonym"].startswith("'=") and ok["hints"] == "'+cmd"
    assert by_url["https://broken.org/b"]["status"] == "failed"
    assert by_url["https://broken.org/b"]["error"] == "URL returned HTTP 404"
    assert rid


def test_refresh_js_is_served_for_both_pages(env: Env) -> None:
    r = env.client.get("/refresh.js")
    assert r.status_code == 200 and "10000" in r.text
    assert 'src="refresh.js"' in env.client.get("/").text
    env.login()
    assert 'src="../refresh.js"' in env.client.get("/admin/").text
