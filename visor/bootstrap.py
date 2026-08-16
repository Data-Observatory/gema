"""Startup config resolution, including first-run seeding of a frozen
(PyInstaller) build's writable config from its bundled read-only default.

visor.spec bundles config/agents.yaml read-only at BUNDLED_CONFIG_SUBPATH
inside the frozen app — it is copied into the user's writable config dir on
first run and never written back into the frozen bundle itself (a
Program-Files-style install or notarized .app is exactly the kind of
location that's unwritable or that Gatekeeper objects to post-install).

That first-run copy also runs through apply_external_user_provider_overrides()
(see below), swapping the testing/deployment provider (opencode) for the
external-user default (openrouter's auto-updating "latest" alias) — a dev
running visor from an editable repo checkout never hits this, since
find_config() finds config/agents.yaml directly first.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

from metadata_enricher.config.loader import find_config, load_config
from metadata_enricher.config.models import DataverseExportConfig, PipelineConfig, ProviderConfig
from metadata_enricher.exporters.dataverse import load_dataverse_export_config
from metadata_enricher.schemas import get_registry
from metadata_enricher.schemas.base import Schema

logger = logging.getLogger(__name__)

BUNDLED_CONFIG_SUBPATH = Path("visor_default_config") / "agents.yaml"
DEFAULT_USER_CONFIG_PATH = Path.home() / ".config" / "metagen" / "agents.yaml"

# Provider/model swap applied only when seeding a frozen build's first-run
# config for a normal external user (see resolve_config_path()'s seeding
# branch below). config/agents.yaml itself -- what CI, tests, and any dev
# running visor from an editable repo checkout all get via find_config() --
# stays pinned to opencode/deepseek-v4-flash, the combination this project
# actually tests and deploys against. The external-user default instead
# points at OpenRouter's own auto-updating "latest" alias, so a fresh
# install never ships an already-stale pinned checkpoint. One source of
# truth for every agent's prompt/fields/tools/depends_on either way --
# this only ever touches provider/model/extra_body.
_TESTING_PROVIDER = "opencode"
_TESTING_MODEL = "deepseek-v4-flash"
_EXTERNAL_USER_PROVIDER = "openrouter"
_EXTERNAL_USER_MODEL = "~deepseek/deepseek-v4-flash-latest"
# OpenRouter's own normalized reasoning-disable param -- different shape
# than DeepSeek's native `thinking: {type: disabled}` passthrough
# config/agents.yaml uses for opencode (see that file's own comment).
_EXTERNAL_USER_EXTRA_BODY = {"reasoning": {"enabled": False}}
_TESTING_EXTRA_BODY = {"thinking": {"type": "disabled"}}


def apply_external_user_provider_overrides(config_yaml: str) -> str:
    """Rewrite config/agents.yaml's testing/deployment provider (opencode)
    to visor's shipped external-user default (openrouter) wherever an
    agent uses it, leaving every other field (prompt, fields, tools,
    depends_on, and any agent already on a different provider) untouched.

    Returns *config_yaml* completely unchanged (not just semantically —
    byte for byte) if it doesn't parse as a mapping, or if it has no
    provider named "openrouter" declared — applying this transform would
    otherwise produce a default_provider/agent.provider referencing a
    provider absent from providers:, which PipelineConfig's own
    cross-validation rejects.
    """
    data = yaml.safe_load(config_yaml)
    if not isinstance(data, dict):
        return config_yaml

    providers = data.get("providers") or []
    provider_names = {p.get("name") for p in providers}
    if _EXTERNAL_USER_PROVIDER not in provider_names:
        return config_yaml

    for provider in providers:
        if provider.get("name") == _TESTING_PROVIDER:
            provider["default"] = False
        elif provider.get("name") == _EXTERNAL_USER_PROVIDER:
            provider["default"] = True

    if data.get("default_provider") == _TESTING_PROVIDER:
        data["default_provider"] = _EXTERNAL_USER_PROVIDER

    for agent in data.get("agents") or []:
        if agent.get("provider") == _TESTING_PROVIDER:
            agent["provider"] = _EXTERNAL_USER_PROVIDER
        if agent.get("model") == _TESTING_MODEL:
            agent["model"] = _EXTERNAL_USER_MODEL
        if agent.get("extra_body") == _TESTING_EXTRA_BODY:
            agent["extra_body"] = dict(_EXTERNAL_USER_EXTRA_BODY)

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

DATAVERSE_EXPORT_BUNDLED_SUBPATH = Path("visor_default_config") / "dataverse_export.yaml"
DATAVERSE_EXPORT_REPO_PATH = Path("config") / "dataverse_export.yaml"

PROVIDERS_POOL_BUNDLED_SUBPATH = Path("visor_default_config") / "providers.yaml"
PROVIDERS_POOL_REPO_PATH = Path("config") / "providers.yaml"


def _bundled_path(subpath: Path) -> Path | None:
    """Where visor.spec bundles a read-only default, if this is a frozen
    build. None when running from source — a repo-relative path already
    covers that case for each of this module's config files."""
    if not getattr(sys, "frozen", False):
        return None
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    candidate = base / subpath
    return candidate if candidate.is_file() else None


def bundled_config_path() -> Path | None:
    """Where visor.spec bundles the read-only default, if this is a frozen
    build. None when running from source — find_config()'s own
    ./config/agents.yaml already covers that case."""
    return _bundled_path(BUNDLED_CONFIG_SUBPATH)


def resolve_config_path(user_config_path: Path | None = None) -> Path:
    """find_config()'s normal search order, plus: if frozen and nothing was
    found, seed the user's writable config dir from the bundled default and
    use that (copy, not a write back into the frozen bundle)."""
    try:
        return find_config()
    except FileNotFoundError:
        bundled = bundled_config_path()
        if bundled is None:
            raise
        target = user_config_path if user_config_path is not None else DEFAULT_USER_CONFIG_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        seeded = apply_external_user_provider_overrides(bundled.read_text(encoding="utf-8"))
        target.write_text(seeded, encoding="utf-8")
        logger.info("Seeded user config at %s from bundled default", target)
        return target


def load_pipeline_config(
    user_config_path: Path | None = None,
) -> tuple[PipelineConfig | None, Schema | None, str | None]:
    """Returns (config, schema, error_message) — exactly one of
    (config and schema) or error_message is set, never a mix."""
    try:
        config = load_config(resolve_config_path(user_config_path))
        schema = get_registry().get(config.schema_name)
    except Exception as exc:  # noqa: BLE001 - surfaced to every page load, not hidden
        logger.exception("Failed to load pipeline configuration")
        return None, None, str(exc)
    return config, schema, None


def dataverse_export_bundled_path() -> Path | None:
    """Same bundling mechanism as bundled_config_path(), separate subpath."""
    return _bundled_path(DATAVERSE_EXPORT_BUNDLED_SUBPATH)


def resolve_dataverse_export_config_path() -> Path:
    """No writable-user-copy step here, unlike resolve_config_path() —
    edits to this config happen in-memory via the Agents tab (session-only,
    same as pipeline_config.agents edits), never written back to any file
    on disk, so there's nothing to seed a user copy from."""
    if DATAVERSE_EXPORT_REPO_PATH.is_file():
        return DATAVERSE_EXPORT_REPO_PATH
    bundled = dataverse_export_bundled_path()
    if bundled is not None:
        return bundled
    msg = f"dataverse_export.yaml not found at {DATAVERSE_EXPORT_REPO_PATH} or bundled"
    raise FileNotFoundError(msg)


def load_dataverse_export_config_safe() -> tuple[DataverseExportConfig | None, str | None]:
    """Returns (config, error_message) — exactly one is set, never a mix.
    Never fatal to the rest of the app if this fails — the Dataverse
    export is an optional extra, not core pipeline functionality."""
    try:
        config = load_dataverse_export_config(resolve_dataverse_export_config_path())
    except Exception as exc:  # noqa: BLE001 - surfaced in the UI, not hidden
        logger.exception("Failed to load Dataverse export configuration")
        return None, str(exc)
    return config, None


def providers_pool_bundled_path() -> Path | None:
    return _bundled_path(PROVIDERS_POOL_BUNDLED_SUBPATH)


def resolve_providers_pool_path() -> Path:
    """Same no-writable-copy reasoning as resolve_dataverse_export_config_path()
    — this file is only ever read, never edited; Settings' "Add a provider"
    picker just offers its entries as autofill presets."""
    if PROVIDERS_POOL_REPO_PATH.is_file():
        return PROVIDERS_POOL_REPO_PATH
    bundled = providers_pool_bundled_path()
    if bundled is not None:
        return bundled
    msg = f"providers.yaml not found at {PROVIDERS_POOL_REPO_PATH} or bundled"
    raise FileNotFoundError(msg)


def load_providers_pool_safe() -> list[ProviderConfig]:
    """Returns [] on any failure — the known-providers pool is a pure UX
    nicety (autofill presets for Settings' "Add a provider" picker); losing
    it must never block Settings from rendering, it just means the "Other
    (custom)" path is the only option."""
    try:
        path = resolve_providers_pool_path()
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return [ProviderConfig.model_validate(p) for p in data["providers"]]
    except Exception:  # noqa: BLE001 - non-fatal by design, see docstring
        logger.exception("Failed to load providers pool — 'Add a provider' will offer custom-only")
        return []
