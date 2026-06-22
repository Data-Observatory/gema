"""Config file loading and discovery.

load_config: read + expand env vars + parse + validate a YAML config file.
find_config: locate a config file using a predefined search order.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from metadata_enricher.config.models import PipelineConfig

logger = logging.getLogger(__name__)


def load_config(path: Path) -> PipelineConfig:
    """Read a YAML config file, expand ``${VAR}`` environment variables,
    parse it, and validate it as a :class:`PipelineConfig`.

    Parameters
    ----------
    path:
        Path to the YAML configuration file.

    Returns
    -------
    PipelineConfig
        Validated pipeline configuration.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    yaml.YAMLError
        If the file is not valid YAML.
    pydantic.ValidationError
        If the parsed content does not satisfy the PipelineConfig schema.
    """
    path = Path(path).resolve()

    if not path.is_file():
        msg = f"config file not found: {path}"
        raise FileNotFoundError(msg)

    raw = path.read_text(encoding="utf-8")
    expanded = os.path.expandvars(raw)
    data = yaml.safe_load(expanded)

    if data is None:
        msg = f"config file is empty or contains only comments: {path}"
        raise ValueError(msg)

    return PipelineConfig.model_validate(data)


def find_config(explicit: Path | None = None) -> Path:
    """Locate a pipeline configuration file using a defined search order.

    Search order
    ------------
    1. *explicit* path (if provided and the file exists).
    2. ``./config/agents.yaml`` (relative to the current working directory).
    3. ``~/.config/metagen/agents.yaml`` (user-level config).
    4. The path stored in the ``METAGEN_CONFIG`` environment variable
       (if set and the file exists).

    Parameters
    ----------
    explicit:
        An optional explicit path to check first.

    Returns
    -------
    Path
        The first configuration file found.

    Raises
    ------
    FileNotFoundError
        If no configuration file could be found at any of the search
        locations.
    """
    candidates: list[Path] = []

    if explicit is not None:
        candidates.append(Path(explicit).resolve())

    candidates.append(Path("config/agents.yaml").resolve())
    candidates.append(Path.home() / ".config" / "metagen" / "agents.yaml")

    env_val = os.environ.get("METAGEN_CONFIG")
    if env_val:
        candidates.append(Path(env_val).resolve())

    for candidate in candidates:
        if candidate.is_file():
            logger.info("found config: %s", candidate)
            return candidate

    searched = "\n  ".join(str(p) for p in candidates)
    msg = f"no configuration file found. Searched:\n  {searched}"
    raise FileNotFoundError(msg)
