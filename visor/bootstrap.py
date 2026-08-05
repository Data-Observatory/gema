"""Startup config resolution, including first-run seeding of a frozen
(PyInstaller) build's writable config from its bundled read-only default.

visor.spec bundles config/agents.yaml read-only at BUNDLED_CONFIG_SUBPATH
inside the frozen app — it is copied into the user's writable config dir on
first run and never written back into the frozen bundle itself (a
Program-Files-style install or notarized .app is exactly the kind of
location that's unwritable or that Gatekeeper objects to post-install).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from metadata_enricher.config.loader import find_config, load_config
from metadata_enricher.config.models import DataverseExportConfig, PipelineConfig
from metadata_enricher.exporters.dataverse import load_dataverse_export_config
from metadata_enricher.schemas import get_registry
from metadata_enricher.schemas.base import Schema

logger = logging.getLogger(__name__)

BUNDLED_CONFIG_SUBPATH = Path("visor_default_config") / "agents.yaml"
DEFAULT_USER_CONFIG_PATH = Path.home() / ".config" / "metagen" / "agents.yaml"

DATAVERSE_EXPORT_BUNDLED_SUBPATH = Path("visor_default_config") / "dataverse_export.yaml"
DATAVERSE_EXPORT_REPO_PATH = Path("config") / "dataverse_export.yaml"


def bundled_config_path() -> Path | None:
    """Where visor.spec bundles the read-only default, if this is a frozen
    build. None when running from source — find_config()'s own
    ./config/agents.yaml already covers that case."""
    if not getattr(sys, "frozen", False):
        return None
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    candidate = base / BUNDLED_CONFIG_SUBPATH
    return candidate if candidate.is_file() else None


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
    if not getattr(sys, "frozen", False):
        return None
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    candidate = base / DATAVERSE_EXPORT_BUNDLED_SUBPATH
    return candidate if candidate.is_file() else None


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
