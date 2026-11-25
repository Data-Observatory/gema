"""GemaRunner without any LLM or network: Pipeline and the exporter are replaced."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import yaml
from intake_app import gema_runner
from intake_app.errors import ConfigError, PermanentError, TransientError
from intake_app.gema_runner import GemaRunner, check_url_reachable
from intake_helpers import make_dataset_json

REPO = Path(__file__).resolve().parents[3]
AGENTS = REPO / "config" / "agents.yaml"
EXPORT = REPO / "config" / "dataverse_export.yaml"


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> GemaRunner:
    monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
    return GemaRunner.from_files(AGENTS, EXPORT, preflight=False)


def test_uses_repo_config_on_opencode_and_aligns_the_classifier(runner: GemaRunner) -> None:
    config, export = runner._config, runner._export  # noqa: SLF001
    assert {a.provider for a in config.agents} == {"opencode"}
    production_model = config.agents[0].model
    assert production_model == "deepseek-v4.1-flash"
    # config/dataverse_export.yaml ships the classifier on openrouter; the intake moves it
    # onto the same opencode provider/model as the production agents.
    assert export.agent.provider == "opencode"
    assert export.agent.model == production_model
    assert export.agent.extra_body == config.agents[0].extra_body


def test_fails_fast_without_opencode_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENCODE_API_KEY"):
        GemaRunner.from_files(AGENTS, EXPORT)


def test_fails_fast_if_an_agent_is_not_on_opencode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
    data = yaml.safe_load(AGENTS.read_text(encoding="utf-8"))
    data["agents"][0]["provider"] = "openrouter"
    bad = tmp_path / "agents.yaml"
    bad.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="opencode only"):
        GemaRunner.from_files(bad, EXPORT)


class FakePipeline:
    """Captures the resource handed to Pipeline.run and returns a canned result."""

    seen: list[Any] = []
    result: Any = None

    def __init__(self, config: Any, max_workers: int = 4) -> None:
        pass

    def run(self, source: Any) -> list[Any]:
        resource = source.fetch(source.list_sources("*")[0])
        FakePipeline.seen.append(resource)
        return [FakePipeline.result]


def ok_result() -> Any:
    return SimpleNamespace(
        success=True, document=object(), error=None, warnings=["pid warning"], resource=None
    )


@pytest.fixture
def fake_pipeline(monkeypatch: pytest.MonkeyPatch) -> type[FakePipeline]:
    FakePipeline.seen = []
    FakePipeline.result = ok_result()
    monkeypatch.setattr(gema_runner, "Pipeline", FakePipeline)
    monkeypatch.setattr(
        gema_runner,
        "to_dataverse_json",
        lambda document, export, provider: SimpleNamespace(
            dataset_json=make_dataset_json(), warnings=["no contact email"]
        ),
    )
    return FakePipeline


def test_hints_become_context_hints_and_url_is_the_only_other_input(
    runner: GemaRunner, fake_pipeline: type[FakePipeline]
) -> None:
    built = runner.build_payload("https://ok.org/x", "Published by the Ministry of Health")
    resource = fake_pipeline.seen[0]
    assert resource.url == "https://ok.org/x"
    assert resource.model_extra == {"context_hints": "Published by the Ministry of Health"}
    assert built.warnings == ["pid warning", "no contact email"]
    assert "datasetVersion" in built.dataset_json


def test_no_hints_means_no_context_hints_key(
    runner: GemaRunner, fake_pipeline: type[FakePipeline]
) -> None:
    runner.build_payload("https://ok.org/x", "   ")
    assert not fake_pipeline.seen[0].model_extra


@pytest.mark.parametrize(
    ("error", "transient"),
    [
        ("All agents failed: Error code: 429 - rate limit", True),
        ("Fields failed: schema_name (Request timed out.)", True),
        ("Orchestration failed: Connection error.", True),
        ("All agents failed: 503 Service Unavailable", True),
        ("Validation failed: Resource must have at least a title", False),
        ("Merge failed: bad shape", False),
    ],
)
def test_pipeline_errors_are_classified(
    runner: GemaRunner, fake_pipeline: type[FakePipeline], error: str, transient: bool
) -> None:
    fake_pipeline.result = SimpleNamespace(success=False, document=None, error=error, warnings=[])
    expected = TransientError if transient else PermanentError
    with pytest.raises(expected):
        runner.build_payload("https://ok.org/x", "")


# -- URL reachability pre-check -------------------------------------------------------------


def stub_stream(monkeypatch: pytest.MonkeyPatch, script: dict[str, tuple[int, str | None]]) -> None:
    @contextmanager
    def stream(method: str, url: str, **kwargs: Any) -> Iterator[Any]:
        status, location = script[url]
        yield SimpleNamespace(
            status_code=status, headers={"location": location} if location else {}
        )

    monkeypatch.setattr(httpx, "stream", stream)
    monkeypatch.setattr(gema_runner, "host_resolves_public", lambda host: host != "internal.test")


def test_reachable_url_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_stream(monkeypatch, {"https://ok.org/x": (200, None)})
    check_url_reachable("https://ok.org/x", allow_private=False)


def test_404_fails_with_a_readable_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_stream(monkeypatch, {"https://gone.org/x": (404, None)})
    with pytest.raises(PermanentError, match="HTTP 404"):
        check_url_reachable("https://gone.org/x", allow_private=False)


def test_5xx_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_stream(monkeypatch, {"https://down.org/x": (503, None)})
    with pytest.raises(TransientError, match="HTTP 503"):
        check_url_reachable("https://down.org/x", allow_private=False)


def test_redirect_is_followed_and_rechecked(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_stream(
        monkeypatch,
        {
            "https://a.org/x": (302, "/y"),
            "https://a.org/y": (301, "http://internal.test/admin"),
        },
    )
    with pytest.raises(PermanentError, match="private"):
        check_url_reachable("https://a.org/x", allow_private=False)


def test_connection_error_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def stream(method: str, url: str, **kwargs: Any) -> Any:
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "stream", stream)
    monkeypatch.setattr(gema_runner, "host_resolves_public", lambda host: True)
    with pytest.raises(TransientError, match="unreachable"):
        check_url_reachable("https://nowhere.org/x", allow_private=False)


def test_dns_failure_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_dns(host: str) -> bool:
        raise OSError("nxdomain")

    monkeypatch.setattr(gema_runner, "host_resolves_public", no_dns)
    with pytest.raises(TransientError, match="DNS"):
        check_url_reachable("https://nxdomain.invalid/x", allow_private=False)
