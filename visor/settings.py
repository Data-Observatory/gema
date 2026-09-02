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
    # Agents-tab overrides, persisted locally so they survive a relaunch --
    # see apply_agent_overrides() below. Keyed by agent ID; each value is a
    # snapshot ({"provider": str, "model": str | None, "temperature": float}),
    # always rewritten in full from the current in-memory PipelineConfig on
    # every save (never merged), so an agent removed by a later config
    # upload never leaves a stale, unreachable entry behind.
    agent_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Same snapshot shape as one agent_overrides entry, plus "enabled" --
    # the Dataverse export's Subject Classifier lives outside
    # pipeline_config.agents (see exporters/dataverse.py), so it needs its
    # own slot rather than a spot in agent_overrides.
    dataverse_agent_override: dict[str, Any] | None = None
    # The Agents tab's "Pipeline behavior" checkboxes (enable_content_fetch,
    # enable_doi_resolution, enable_identifier_enrichment, validate_pids,
    # validate_pids_live) -- PipelineConfig-level, not per-agent.
    pipeline_behavior: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_provider": self.default_provider,
            "env": dict(self.env),
            "agent_overrides": {k: dict(v) for k, v in self.agent_overrides.items()},
            "dataverse_agent_override": (
                dict(self.dataverse_agent_override)
                if self.dataverse_agent_override is not None
                else None
            ),
            "pipeline_behavior": dict(self.pipeline_behavior),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisorSettings:
        env = data.get("env")
        agent_overrides = data.get("agent_overrides")
        dataverse_agent_override = data.get("dataverse_agent_override")
        pipeline_behavior = data.get("pipeline_behavior")
        return cls(
            default_provider=data.get("default_provider"),
            env=dict(env) if isinstance(env, dict) else {},
            agent_overrides=(
                {k: dict(v) for k, v in agent_overrides.items() if isinstance(v, dict)}
                if isinstance(agent_overrides, dict)
                else {}
            ),
            dataverse_agent_override=(
                dict(dataverse_agent_override)
                if isinstance(dataverse_agent_override, dict)
                else None
            ),
            pipeline_behavior=(
                dict(pipeline_behavior) if isinstance(pipeline_behavior, dict) else {}
            ),
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


def agents_using_provider(pipeline_config: PipelineConfig, provider_name: str) -> list[str]:
    """Agent IDs assigned to exactly *provider_name* -- unlike
    providers_using() below, never widened to "every provider sharing this
    one's api_key_env". Settings' per-row "used by" caption and its
    unassigned-key nudge both need this narrower, name-scoped answer: two
    providers can legitimately share one env var (see
    missing_required_details()'s docstring), and attributing one
    provider's agents to the other's row -- or suppressing the nudge for
    a genuinely unused provider just because a same-keyed sibling is
    used -- would be the same misattribution bug this module already
    fixed once for the Run gate, resurfacing here."""
    return sorted(a.id for a in pipeline_config.agents if a.provider == provider_name)


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


PIPELINE_BEHAVIOR_FLAGS = (
    "enable_content_fetch",
    "enable_doi_resolution",
    "enable_identifier_enrichment",
    "validate_pids",
    "validate_pids_live",
)


def apply_agent_overrides(
    pipeline_config: PipelineConfig,
    dataverse_export_config: DataverseExportConfig | None,
    settings: VisorSettings,
) -> None:
    """Layer a user's saved Agents-tab choices on top of the freshly loaded
    PipelineConfig -- the third and final layer after config/agents.yaml
    (canonical, shared, opencode-pinned) and
    bootstrap.apply_external_user_provider_overrides() (visor's openrouter
    swap). config/agents.yaml itself is never written to (see this module's
    docstring); this only mutates the in-memory copy each browser session
    already gets from app.py's model_copy(deep=True).

    Every override is applied defensively, field by field, so a stale or
    hand-edited settings.json can never make this raise or leave
    pipeline_config in a state PipelineConfig's own validators would have
    rejected:
    - an agent_overrides entry for an agent ID no longer in
      pipeline_config.agents (e.g. after a repo agents.yaml change) is
      simply unreachable and ignored;
    - a saved provider name no longer in pipeline_config.providers is
      skipped (leaving that agent's provider as the loaded config's own),
      while model/temperature from the same entry still apply.
    """
    provider_names = {p.name for p in pipeline_config.providers}

    for agent in pipeline_config.agents:
        override = settings.agent_overrides.get(agent.id)
        if not override:
            continue
        provider = override.get("provider")
        if isinstance(provider, str) and provider in provider_names:
            agent.provider = provider
        if "model" in override:
            model = override["model"]
            agent.model = model if isinstance(model, str) and model else None
        temperature = override.get("temperature")
        if isinstance(temperature, int | float):
            agent.temperature = float(temperature)

    dataverse_override = settings.dataverse_agent_override
    if dataverse_export_config is not None and dataverse_override:
        enabled = dataverse_override.get("enabled")
        if isinstance(enabled, bool):
            dataverse_export_config.enabled = enabled
        provider = dataverse_override.get("provider")
        if isinstance(provider, str) and provider in provider_names:
            dataverse_export_config.agent.provider = provider
        if "model" in dataverse_override:
            model = dataverse_override["model"]
            dataverse_export_config.agent.model = model if isinstance(model, str) and model else None
        temperature = dataverse_override.get("temperature")
        if isinstance(temperature, int | float):
            dataverse_export_config.agent.temperature = float(temperature)

    for flag in PIPELINE_BEHAVIOR_FLAGS:
        value = settings.pipeline_behavior.get(flag)
        if isinstance(value, bool):
            setattr(pipeline_config, flag, value)


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

    Grouped by provider *name*, not by api_key_env: nothing enforces
    api_key_env uniqueness across providers (Settings' "Add a provider"
    lets a user type any env var name, including one already in use), and
    two distinct providers can legitimately share one env var (e.g. the
    same account key against two base_urls). Grouping by env var would
    either drop or misattribute one of them whenever both are actually
    used -- grouping by name keeps every genuinely-used provider on its
    own line even when two lines end up naming the same env var. A
    provider with no agent actually assigned to it is skipped entirely,
    regardless of whether its api_key_env matches another provider's.
    """
    missing_envs = set(missing_required(pipeline_config, settings))
    if not missing_envs:
        return []
    by_provider: dict[str, MissingKeyDetail] = {}
    for provider in pipeline_config.providers:
        if provider.api_key_env not in missing_envs:
            continue
        agent_ids = [a.id for a in pipeline_config.agents if a.provider == provider.name]
        if not agent_ids:
            continue
        detail = by_provider.setdefault(
            provider.name,
            MissingKeyDetail(api_key_env=provider.api_key_env, provider=provider.name, agent_ids=[]),
        )
        detail.agent_ids.extend(agent_ids)
    return [by_provider[name] for name in sorted(by_provider)]
