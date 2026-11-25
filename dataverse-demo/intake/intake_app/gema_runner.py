"""GEMA! side: URL -> CDIF document -> Dataverse-native dataset JSON, via the Python library.

No Visor, no GUI. The repo's own ``config/agents.yaml`` is reused unchanged (production
model, content fetch and identifier enrichment as configured there); this module only
asserts it is on the ``opencode`` provider and points the Dataverse Subject classifier at
that same provider/model (``config/dataverse_export.yaml`` ships it on openrouter).
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from metadata_enricher.config.loader import load_config
from metadata_enricher.config.models import DataverseExportConfig, PipelineConfig, ProviderConfig
from metadata_enricher.exporters.dataverse import load_dataverse_export_config, to_dataverse_json
from metadata_enricher.pipeline import Pipeline
from metadata_enricher.types import ResourceDescription

from intake_app.errors import ConfigError, PermanentError, StepError, TransientError
from intake_app.urls import host_resolves_public

logger = logging.getLogger(__name__)

PROVIDER = "opencode"
USER_AGENT = "Mozilla/5.0 (compatible; gema-intake/1.0)"
_MAX_REDIRECTS = 5

# Pipeline errors are plain strings (PipelineResult.error); these mark the ones that are
# worth a retry (provider/network hiccups) as opposed to e.g. a validation failure.
_TRANSIENT_RE = re.compile(
    r"timed? ?out|timeout|connection|rate.?limit|\b429\b|\b5\d\d\b|temporar|unavailable|overload",
    re.IGNORECASE,
)


@dataclass
class BuiltPayload:
    dataset_json: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


class PayloadBuilder(Protocol):
    def build_payload(self, url: str, hints: str) -> BuiltPayload:
        """Run everything up to (not including) the Dataverse upload."""


class _OneShotSource:
    """Feeds one in-memory resource to ``Pipeline.run`` (the public entry point)."""

    def __init__(self, resource: ResourceDescription) -> None:
        self._resource = resource

    def list_sources(self, pattern: str) -> list[str]:
        return ["intake"]

    def fetch(self, source: str) -> ResourceDescription:
        return self._resource


def check_url_reachable(url: str, *, allow_private: bool, timeout: float = 15.0) -> None:
    """Fail fast, with a readable reason, on a dead/forbidden URL.

    GEMA!'s own page fetch is best-effort by design (a dead URL silently yields no page
    text and the model would then describe a page it never saw), so the intake checks
    reachability itself. Each redirect hop is re-checked against the private-address guard.
    """
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        host = urlsplit(current).hostname or ""
        if not allow_private:
            try:
                public = host_resolves_public(host)
            except OSError as exc:
                raise TransientError(f"DNS lookup failed for {host}") from exc
            if not public:
                raise PermanentError("URL points to a private/internal address")
        try:
            with httpx.stream(
                "GET",
                current,
                follow_redirects=False,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            ) as resp:
                status = resp.status_code
                location = resp.headers.get("location")
        except httpx.InvalidURL:
            raise PermanentError("invalid URL") from None
        except httpx.TimeoutException as exc:
            raise TransientError(f"URL timed out ({timeout:.0f}s)") from exc
        except httpx.TransportError as exc:
            raise TransientError(f"URL unreachable ({type(exc).__name__})") from exc
        if 300 <= status < 400 and location:
            current = urljoin(current, location)
            continue
        if status == 429 or status >= 500:
            raise TransientError(f"URL returned HTTP {status}")
        if status >= 400:
            raise PermanentError(f"URL returned HTTP {status}")
        return
    raise PermanentError("URL redirects too many times")


def _classify(error: str) -> StepError:
    text = error.replace("\n", " ")[:300]
    return TransientError(text) if _TRANSIENT_RE.search(text) else PermanentError(text)


class GemaRunner:
    """Builds the Dataverse payload for one resource. One ``Pipeline`` per call: it is cheap
    to construct and keeps enrichers' state out of the worker threads."""

    def __init__(
        self,
        pipeline_config: PipelineConfig,
        export_config: DataverseExportConfig,
        provider: ProviderConfig,
        *,
        preflight: bool = True,
        allow_private_urls: bool = False,
    ) -> None:
        self._config = pipeline_config
        self._export = export_config
        self._provider = provider
        self._preflight = preflight
        self._allow_private = allow_private_urls

    @classmethod
    def from_files(
        cls,
        config_path: Path,
        export_config_path: Path,
        *,
        preflight: bool = True,
        allow_private_urls: bool = False,
    ) -> GemaRunner:
        """Load the repo config and fail fast on anything that would break every record."""
        if not os.environ.get("OPENCODE_API_KEY", "").strip():
            raise ConfigError("OPENCODE_API_KEY is not set")
        try:
            config = load_config(config_path)
            export = load_dataverse_export_config(export_config_path)
        except Exception as exc:
            raise ConfigError(f"cannot load GEMA! config: {exc}") from exc

        provider = next((p for p in config.providers if p.name == PROVIDER), None)
        if provider is None:
            raise ConfigError(f"provider {PROVIDER!r} is not defined in {config_path}")
        others = sorted({a.provider for a in config.agents if a.provider != PROVIDER})
        if others:
            raise ConfigError(
                f"{config_path} has agents on {others}; the intake runs opencode only "
                "(the production provider). Use the repo default config."
            )

        # Same model/extra_body as the production agents, not a model of our own choosing.
        models = Counter(a.model for a in config.agents if a.model)
        if not models:
            raise ConfigError("no agent in the GEMA! config names a model")
        model = models.most_common(1)[0][0]
        donor = next(a for a in config.agents if a.model == model)
        export.agent = export.agent.model_copy(
            update={"provider": PROVIDER, "model": model, "extra_body": donor.extra_body}
        )
        logger.info("gema runner: provider=%s model=%s", PROVIDER, model)
        return cls(
            config, export, provider, preflight=preflight, allow_private_urls=allow_private_urls
        )

    def build_payload(self, url: str, hints: str) -> BuiltPayload:
        if self._preflight:
            check_url_reachable(url, allow_private=self._allow_private)

        # `context_hints` is the repo's existing mechanism for externally supplied facts:
        # ResourceDescription allows extra fields, agents/base.py forwards them to the
        # prompt, and the shared system prompt tells every agent how to treat them.
        extra: dict[str, str] = {"context_hints": hints} if hints.strip() else {}
        resource = ResourceDescription(url=url, **extra)

        model = self._export.agent.model
        workers = self._config.effective_max_workers(PROVIDER, model)
        pipeline = Pipeline(self._config, max_workers=workers)
        results = pipeline.run(_OneShotSource(resource))
        if not results:
            raise PermanentError("GEMA! returned no result")
        result = results[0]
        if not result.success or result.document is None:
            raise _classify(result.error or "GEMA! produced no document")

        try:
            exported = to_dataverse_json(result.document, self._export, self._provider)
        except Exception as exc:
            raise _classify(f"Dataverse export failed: {type(exc).__name__}: {exc}") from exc
        return BuiltPayload(
            dataset_json=exported.dataset_json, warnings=[*result.warnings, *exported.warnings]
        )
