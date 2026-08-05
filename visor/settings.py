"""Local, per-user secrets storage for visor.

Deliberately separate from ``~/.config/metagen/agents.yaml`` (the pipeline
behavior config a non-programmer must never hand-edit — see
``metadata_enricher.config.loader.find_config``). This module owns a small
JSON file holding only secrets (API keys, ORCID credentials) and the
selected default provider, keyed by the same ``api_key_env`` strings the
effective ``agents.yaml`` already declares.

Never writes to ``.env`` or ``config/agents.yaml`` — those are repo/dev
conventions, not end-user secret storage.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from metadata_enricher.config.models import PipelineConfig

logger = logging.getLogger(__name__)

APP_NAME = "metagen-visor"
SETTINGS_FILENAME = "settings.json"

# Read directly by metadata_enricher.enrichers.orcid_client via os.environ —
# not part of any ProviderConfig, so they can't be derived from agents.yaml.
ORCID_ENV_VARS = ("ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET")


@dataclass
class VisorSettings:
    default_provider: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"default_provider": self.default_provider, "env": dict(self.env)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisorSettings:
        env = data.get("env")
        return cls(
            default_provider=data.get("default_provider"),
            env=dict(env) if isinstance(env, dict) else {},
        )


def settings_path() -> Path:
    """Where the local settings.json lives — resolves correctly on Windows
    (%APPDATA%), macOS (~/Library/Application Support), and Linux (XDG)."""
    return Path(user_config_dir(APP_NAME)) / SETTINGS_FILENAME


def load_settings(path: Path | None = None) -> VisorSettings:
    """Load settings.json, or an empty VisorSettings if it doesn't exist yet."""
    target = path if path is not None else settings_path()
    if not target.is_file():
        return VisorSettings()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read visor settings at %s: %s — using empty settings", target, exc)
        return VisorSettings()
    if not isinstance(data, dict):
        return VisorSettings()
    return VisorSettings.from_dict(data)


def save_settings(settings: VisorSettings, path: Path | None = None) -> None:
    """Write settings.json, restricting permissions to the owner where the OS honors it."""
    target = path if path is not None else settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    try:
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        logger.debug("Could not restrict permissions on %s (unsupported on this OS)", target)


def required_env_vars(pipeline_config: PipelineConfig) -> list[str]:
    """Env vars actually needed to run every agent in the effective config —
    derived, never hardcoded, so this stays in sync if agents.yaml changes.

    Deliberately scoped to providers referenced by at least one agent's
    `provider` field, not every provider merely *declared* in the config's
    `providers:` list — agents.yaml commonly lists several available
    providers (e.g. as documented alternatives) while every agent actually
    uses just one. Asking a non-programmer for keys to providers nothing
    will ever call would be a real, avoidable papercut.
    """
    used_provider_names = {a.provider for a in pipeline_config.agents}
    by_name = {p.name: p.api_key_env for p in pipeline_config.providers}
    return sorted({by_name[name] for name in used_provider_names if name in by_name})


def optional_env_vars() -> list[str]:
    """Env vars that unlock optional features (ORCID search-by-name) but
    whose absence is a silent no-op, never a failure."""
    return list(ORCID_ENV_VARS)


def apply_to_environ(settings: VisorSettings) -> None:
    """Inject saved secrets into the process environment.

    This is the one seam metadata_enricher.llm.factory._resolve_api_key
    actually reads from (os.environ.get(api_key_env)) — ProviderConfig takes
    a variable *name*, not a value, so there is no other injection point
    without an upstream change. Call before constructing any PipelineConfig
    used to build a Pipeline.
    """
    for key, value in settings.env.items():
        if value:
            os.environ[key] = value


def missing_required(pipeline_config: PipelineConfig, settings: VisorSettings) -> list[str]:
    """Required env vars with no non-empty value in *settings* — used to
    gate the run form behind Settings on first use, instead of letting
    factory.py's raw ValueError surface."""
    return [env for env in required_env_vars(pipeline_config) if not settings.env.get(env)]
