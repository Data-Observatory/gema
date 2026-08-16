"""Tool definitions and executors for the agentic tool-call loop.

Only agents that explicitly opt in via ``AgentConfig.tools`` ever see any of
this — every other agent's request has no ``tools=`` at all, so this module
has zero effect on them. See ``InstructorLLMClient.complete_with_tools``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from metadata_enricher.enrichers.ror_client import RORClient, get_display_name

logger = logging.getLogger(__name__)

# One shared instance -- stateless besides its own httpx.Client connection
# pool, same singleton pattern as agents/base.py's _country_extractor.
_ror_client = RORClient()

_ROR_LOOKUP_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "lookup_organization",
        "description": (
            "Look up an organization name in ROR (Research Organization Registry) "
            "to confirm its canonical name before using it as a creator, publisher, "
            "or affiliation. Use this when you are unsure of an organization's exact "
            "official name or hierarchy. Returns the best-matching canonical name, "
            "or found=false if there is no confident match."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Organization name or affiliation string to look up.",
                }
            },
            "required": ["name"],
        },
    },
}


def _execute_lookup_organization(arguments: dict[str, Any]) -> str:
    name = arguments.get("name", "")
    if not isinstance(name, str) or not name.strip():
        return json.dumps({"found": False})
    try:
        org = _ror_client.search_affiliation(name)
        if org is None:
            results = _ror_client.search_query(name, limit=1)
            org = results[0] if results else None
    except Exception as exc:  # noqa: BLE001 - a failed lookup must not crash the agent
        logger.warning("ROR lookup failed for %r: %s", name, exc)
        return json.dumps({"found": False})
    if org is None:
        return json.dumps({"found": False})
    return json.dumps({"found": True, "canonical_name": get_display_name(org)})


# Maps a tool name (as declared in AgentConfig.tools) to its OpenAI-style
# function schema and its executor. Keyed by name only -- unlike
# ModelOverride, there is exactly one global tool implementation per name,
# not one scoped per provider.
TOOL_REGISTRY: dict[str, tuple[dict[str, Any], Callable[[dict[str, Any]], str]]] = {
    "lookup_organization": (_ROR_LOOKUP_SCHEMA, _execute_lookup_organization),
}


def tool_schemas(names: list[str]) -> list[dict[str, Any]]:
    """Return the OpenAI-style function schemas for the given tool names."""
    return [TOOL_REGISTRY[name][0] for name in names]


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a registered tool by name, returning its JSON string result.

    Never raises: an unknown tool name or a failed lookup both return a
    ``{"found": false}``-shaped JSON string, since this result is fed back
    to the model as a tool message, not surfaced as a pipeline error.
    """
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        logger.warning("Unknown tool %r requested by model; ignoring.", name)
        return json.dumps({"found": False})
    _, executor = entry
    return executor(arguments)
