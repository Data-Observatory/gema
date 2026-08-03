"""Migrate legacy JSON configuration to the current YAML PipelineConfig format.

The legacy format (``andrea_v3.json``) stores agent definitions with
``output_fields``, ``prompt_template``, and a nested ``llm_config`` dict.
Provider configurations live in a sibling ``providers.json`` file.

This module converts those legacy files into a single YAML file that
validates against :class:`PipelineConfig`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DIRECT_FIELDS = frozenset({"id", "name", "description", "depends_on", "use_chain_of_thought"})

_RENAMED_FIELDS = {
    "output_fields": "fields",
    "prompt_template": "prompt",
}


def _load_providers(providers_path: Path) -> list[dict[str, Any]]:
    """Load and convert the legacy ``providers.json`` file.

    Maps ``api_base`` → ``base_url``.
    """
    if not providers_path.is_file():
        logger.info("no providers file found at %s", providers_path)
        return []

    raw = json.loads(providers_path.read_text(encoding="utf-8"))
    providers_data = raw.get("providers", raw)
    result: list[dict[str, Any]] = []

    for name, cfg in providers_data.items():
        entry: dict[str, Any] = {"name": name, "api_key_env": cfg["api_key_env"]}
        api_base = cfg.get("api_base")
        if api_base is not None:
            entry["base_url"] = api_base
        result.append(entry)

    return result


def _convert_agent(old: dict[str, Any]) -> dict[str, Any]:
    """Convert a single legacy agent dict to the new format."""
    new: dict[str, Any] = {}

    for key, value in old.items():
        if key in _DIRECT_FIELDS:
            new[key] = value
        elif key in _RENAMED_FIELDS:
            new[_RENAMED_FIELDS[key]] = value
        elif key == "llm_config":
            if isinstance(value, dict):
                new.setdefault("model", value.get("model"))
                new.setdefault("provider", value.get("provider"))
                new.setdefault("temperature", value.get("temperature", 0.0))
                new.setdefault("max_tokens", value.get("max_tokens"))
            else:
                logger.warning("llm_config is not a dict, skipping: %s", value)
        else:
            logger.warning("ignoring unknown field in agent '%s': %s", old.get("id", "?"), key)

    return new


def migrate_json_to_yaml(json_path: Path) -> Path:
    """Convert a legacy JSON config file to the new YAML ``PipelineConfig`` format.

    Parameters
    ----------
    json_path:
        Path to the legacy JSON configuration file (e.g. ``config/andrea_v3.json``).

    Returns
    -------
    Path
        Path to the newly created YAML file (same directory, ``.yaml`` extension).

    Notes
    -----
    - The original JSON file is **never** modified.
    - A sibling ``providers.json`` file is loaded automatically if present.
    - ``schema_name`` is hard-coded to ``"datacite-4.6"``.
    - ``default_provider`` is set to the first provider name referenced by
      the agents (alphabetically for determinism).
    """
    json_path = Path(json_path).resolve()
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    old_agents = raw.get("agents", raw)

    new_agents = [_convert_agent(a) for a in old_agents]

    agent_providers: set[str] = set()
    for a in new_agents:
        prov = a.get("provider")
        if prov:
            agent_providers.add(prov)

    providers_path = json_path.parent / "providers.json"
    new_providers = _load_providers(providers_path)

    pipeline: dict[str, Any] = {
        "schema_name": "datacite-4.6",
        "agents": new_agents,
        "providers": new_providers,
    }

    if agent_providers:
        pipeline["default_provider"] = sorted(agent_providers)[0]

    yaml_path = json_path.with_suffix(".yaml")
    with yaml_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(pipeline, f, allow_unicode=True, sort_keys=False)

    logger.info("migrated %s → %s", json_path, yaml_path)

    return yaml_path
