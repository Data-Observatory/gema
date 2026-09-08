"""Startup config resolution, including first-run seeding of a frozen
(PyInstaller) build's writable config from its bundled read-only default.

visor.spec bundles config/agents.yaml read-only at BUNDLED_CONFIG_SUBPATH
inside the frozen app — it is copied into the user's writable config dir on
first run and never written back into the frozen bundle itself (a
Program-Files-style install or notarized .app is exactly the kind of
location that's unwritable or that Gatekeeper objects to post-install).

Separately, load_pipeline_config() always runs whatever config it resolved
through apply_external_user_provider_overrides() (see below) before
validating it — visor's own default provider is openrouter every time it
boots, whether it found config/agents.yaml directly (running from an
editable repo checkout) or a frozen build's seeded copy. Only the
underlying files (config/agents.yaml, and any seeded user copy of it) stay
pinned to opencode/deepseek-v4-flash on disk — that's what CI, the test
suite, and `gema process` from the CLI actually run against.

That openrouter default is meant for someone with no opencode access at
all, not an unconditional override -- restore_testing_provider_if_key_available()
(see below) undoes it, per session, for anyone whose environment already
has a real key for the testing provider (e.g. a maintainer's own .env,
loaded process-wide by `uv run` the same way the CLI sees it). Confirmed
2026-09-08: without this, someone with working opencode access got
silently rerouted through openrouter's model alias and its differently
-shaped reasoning-disable param, which doesn't reliably suppress
thinking-mode there and collides with a forced tool_choice -- a bug the
canonical opencode config (proven reliable via the CLI) never hits. Called
from app.py, after settings.apply_to_environ() so a hosted session's own
saved key is visible in the same os.environ check a native install's .env
already populated.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import yaml

from metadata_enricher.config.loader import find_config, load_config
from metadata_enricher.config.models import DataverseExportConfig, PipelineConfig, ProviderConfig
from metadata_enricher.exporters.dataverse import load_dataverse_export_config
from metadata_enricher.schemas import get_registry
from metadata_enricher.schemas.base import Schema

logger = logging.getLogger(__name__)

BUNDLED_CONFIG_SUBPATH = Path("visor_default_config") / "agents.yaml"
DEFAULT_USER_CONFIG_PATH = Path.home() / ".config" / "gema" / "agents.yaml"

# Provider/model swap applied by load_pipeline_config() to every config
# visor loads, regardless of where it came from. config/agents.yaml (and
# any file seeded from it) stays pinned to opencode/deepseek-v4-flash on
# disk -- the combination CI/tests/the CLI actually run against, i.e.
# "working on this library". Visor is everywhere else: its own default
# is always OpenRouter's auto-updating "latest" alias, so a fresh install
# never ships an already-stale pinned checkpoint. One source of truth for
# every agent's prompt/fields/tools/depends_on either way -- this only
# ever touches provider/model/extra_body, and only in memory.
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


def restore_testing_provider_if_key_available(pipeline_config: PipelineConfig) -> None:
    """Undo apply_external_user_provider_overrides()'s openrouter swap, per
    session, for any agent still sitting on the external-user default --
    but only when a real key for the testing provider (opencode) is
    already available in this process's environment. Call after
    settings.apply_to_environ(settings) (so a hosted session's own saved
    key has already been copied in) and before apply_agent_overrides() (so
    a user's own explicit saved provider/model choice, applied after this,
    still wins over both defaults).

    Inverts the swap using the same well-known constants rather than
    needing a second, unswapped copy of the config kept around --
    conservative by construction (only restores an agent whose provider,
    model, *and* extra_body all still exactly match the external-user
    default), so a config that already diverged from that shape (e.g. an
    agent bulk-switched to a third provider) is left alone.

    A user's own saved provider/model choice, applied by
    apply_agent_overrides() right after this, still wins -- but extra_body
    isn't one of the fields that function restores, so it can end up
    stale relative to whatever (provider, model) that later layer settles
    on; call reconcile_provider_extra_body() (below) last, after
    apply_agent_overrides(), to fix that up.

    A no-op (safe) when the config doesn't declare the testing provider at
    all, or when nothing was actually swapped (e.g. a hand-edited config
    already using an agent on a third, unrelated provider).
    """
    testing_provider = next(
        (p for p in pipeline_config.providers if p.name == _TESTING_PROVIDER), None
    )
    if testing_provider is None or not os.environ.get(testing_provider.api_key_env):
        return

    restored_any = False
    for agent in pipeline_config.agents:
        if (
            agent.provider == _EXTERNAL_USER_PROVIDER
            and agent.model == _EXTERNAL_USER_MODEL
            and agent.extra_body == _EXTERNAL_USER_EXTRA_BODY
        ):
            agent.provider = _TESTING_PROVIDER
            agent.model = _TESTING_MODEL
            agent.extra_body = dict(_TESTING_EXTRA_BODY)
            restored_any = True

    if not restored_any:
        return

    if pipeline_config.default_provider == _EXTERNAL_USER_PROVIDER:
        pipeline_config.default_provider = _TESTING_PROVIDER
    for provider in pipeline_config.providers:
        if provider.name == _TESTING_PROVIDER:
            provider.default = True
        elif provider.name == _EXTERNAL_USER_PROVIDER:
            provider.default = False


def reconcile_provider_extra_body(pipeline_config: PipelineConfig) -> None:
    """Fix up extra_body left stale by a later layer changing (provider,
    model) without also updating it -- apply_agent_overrides() (settings.py)
    restores a user's own saved provider/model choice but was never meant
    to know about this swap's extra_body shapes, so a session that
    restore_testing_provider_if_key_available() flipped to opencode, whose
    saved override then flips the same agent back to openrouter (e.g.
    saved before this session ever had an opencode key), ends up with
    openrouter's provider/model paired with opencode's DeepSeek-native
    extra_body -- OpenRouter doesn't understand that shape, thinking mode
    stays on, and it collides with a forced tool_choice exactly like the
    bug this branch exists to eliminate. Call this last, after
    apply_agent_overrides(), so it reconciles whichever (provider, model)
    pair actually won.

    Equality-gated the same conservative way as the swap/restore
    functions above: only touches extra_body that's still sitting at
    exactly the *other* pairing's canonical shape, so a genuinely
    hand-customized extra_body (e.g. via the Agents tab's JSON upload) on
    an agent that happens to already match one of these (provider, model)
    pairs is left alone.
    """
    for agent in pipeline_config.agents:
        if (
            agent.provider == _TESTING_PROVIDER
            and agent.model == _TESTING_MODEL
            and agent.extra_body == _EXTERNAL_USER_EXTRA_BODY
        ):
            agent.extra_body = dict(_TESTING_EXTRA_BODY)
        elif (
            agent.provider == _EXTERNAL_USER_PROVIDER
            and agent.model == _EXTERNAL_USER_MODEL
            and agent.extra_body == _TESTING_EXTRA_BODY
        ):
            agent.extra_body = dict(_EXTERNAL_USER_EXTRA_BODY)


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
        target.write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("Seeded user config at %s from bundled default", target)
        return target


def load_pipeline_config(
    user_config_path: Path | None = None,
) -> tuple[PipelineConfig | None, Schema | None, str | None]:
    """Returns (config, schema, error_message) — exactly one of
    (config and schema) or error_message is set, never a mix.

    Whatever config_path resolves to (config/agents.yaml directly, or a
    frozen build's seeded copy), the text is run through
    apply_external_user_provider_overrides() before validation -- visor's
    own default is always OpenRouter, regardless of how its config file
    was found. The transformed text is written to a throwaway temp file
    and handed to load_config() so ${VAR} expansion and validation stay
    byte-for-byte the same codepath every other caller of load_config()
    uses -- no parsing logic duplicated here.
    """
    try:
        config_path = resolve_config_path(user_config_path)
        transformed = apply_external_user_provider_overrides(
            config_path.read_text(encoding="utf-8")
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(transformed)
            tmp_path = Path(tmp.name)
        try:
            config = load_config(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
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
