"""Local, per-user secrets storage for visor.

Deliberately separate from ``~/.config/gema/agents.yaml`` (the pipeline
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
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from metadata_enricher.config.models import DataverseExportConfig, PipelineConfig, ProviderConfig

logger = logging.getLogger(__name__)

APP_NAME = "gema-visor"
SETTINGS_FILENAME = "settings.json"
STORAGE_SECRET_FILENAME = "storage_secret.txt"

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


def storage_secret() -> str:
    """Key NiceGUI's app.storage.user (a signed per-browser cookie, used for
    the language preference) with -- generated once and persisted next to
    settings.json so existing cookies keep working across restarts, instead
    of a fresh random key on every process start forcing every browser back
    to the default language. Not a secret in the API-key sense: it only
    signs a language-preference cookie, so sharing it across every session
    on this machine (hosted or native) is fine."""
    path = Path(user_config_dir(APP_NAME)) / STORAGE_SECRET_FILENAME
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    secret = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secret, encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        logger.debug("Could not restrict permissions on %s (unsupported on this OS)", path)
    return secret


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


def all_provider_env_vars(pipeline_config: PipelineConfig) -> list[str]:
    """Every declared provider's api_key_env, not just the ones an agent
    currently uses — for Settings' key-entry list. required_env_vars()
    stays scoped to "actually needed right now" for the Run-tab gate;
    this one is deliberately broader: switching an agent's provider in the
    Agents tab (e.g. to opencode) must not leave no way to ever enter that
    provider's key."""
    return sorted({p.api_key_env for p in pipeline_config.providers})


def providers_using(pipeline_config: PipelineConfig, api_key_env: str) -> list[str]:
    """Agent IDs currently assigned to whichever provider(s) resolve to
    *api_key_env* — for Settings' "used by: ..." caption.

    Deliberately walks pipeline_config.agents only, never the Dataverse
    export's Subject Classifier (a separate, optional LLM step outside
    pipeline_config.agents — see exporters/dataverse.py). A caller that
    also needs to know about that one extra consumer (Settings' caption,
    the remove-provider block) checks dataverse_uses_provider() alongside
    this.
    """
    provider_names = {p.name for p in pipeline_config.providers if p.api_key_env == api_key_env}
    return sorted(a.id for a in pipeline_config.agents if a.provider in provider_names)


def dataverse_uses_provider(
    dataverse_export_config: DataverseExportConfig | None, provider_name: str
) -> bool:
    """Whether the Dataverse export's Subject Classifier is assigned to
    *provider_name* — see providers_using()'s docstring for why this is
    a separate check."""
    return dataverse_export_config is not None and dataverse_export_config.agent.provider == provider_name


def addable_providers(
    known_providers: list[ProviderConfig], pipeline_config: PipelineConfig
) -> list[ProviderConfig]:
    """Known-pool entries not already in pipeline_config.providers — what
    Settings' "Add a provider" picker offers as presets. Pulled out as its
    own function (rather than inlined in settings_page.py) specifically so
    it's testable without booting the whole app — the real default config
    (config/agents.yaml) already declares every pool entry, so a full
    click-through test can never actually exercise "a pool entry that's
    still addable" against it.
    """
    existing_names = {p.name for p in pipeline_config.providers}
    return [p for p in known_providers if p.name not in existing_names]


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


@dataclass
class MissingKeyDetail:
    """One missing key, attributed to the provider and agent(s) that
    actually need it — what the Run tab's gate shows instead of a bare
    env var name, so switching an agent to a new provider (e.g. opencode)
    tells you exactly which key that switch now requires, rather than an
    unexplained env var appearing in a flat list."""

    api_key_env: str
    provider: str
    agent_ids: list[str]


def missing_required_details(
    pipeline_config: PipelineConfig, settings: VisorSettings
) -> list[MissingKeyDetail]:
    """Same gate as missing_required(), grouped by provider/agent instead
    of a flat env-var list.

    Skips a provider with no agent actually assigned to it even when its
    api_key_env matches: two distinct ProviderConfig entries (nothing
    enforces api_key_env uniqueness -- Settings' "Add a provider" lets a
    user type any env var name, including one already in use) can share
    one env var while only one of them is actually referenced by an
    agent. Attributing the gate to whichever happened to be declared
    first in pipeline_config.providers, regardless of use, would name
    the wrong provider.
    """
    missing_envs = set(missing_required(pipeline_config, settings))
    if not missing_envs:
        return []
    by_env: dict[str, MissingKeyDetail] = {}
    for provider in pipeline_config.providers:
        if provider.api_key_env not in missing_envs:
            continue
        agent_ids = [a.id for a in pipeline_config.agents if a.provider == provider.name]
        if not agent_ids:
            continue
        detail = by_env.setdefault(
            provider.api_key_env,
            MissingKeyDetail(api_key_env=provider.api_key_env, provider=provider.name, agent_ids=[]),
        )
        detail.agent_ids.extend(agent_ids)
    return [by_env[env] for env in sorted(by_env)]
