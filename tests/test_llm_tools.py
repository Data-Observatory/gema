"""Tests for llm/tools.py's tool registry and executors."""

from __future__ import annotations

import json
from unittest.mock import patch

from metadata_enricher.llm.tools import (
    TOOL_REGISTRY,
    execute_tool,
    tool_schemas,
)


class TestToolSchemas:
    def test_returns_schema_for_known_tool(self) -> None:
        schemas = tool_schemas(["lookup_organization"])
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "lookup_organization"

    def test_preserves_order_and_allows_repeats(self) -> None:
        schemas = tool_schemas(["lookup_organization", "lookup_organization"])
        assert len(schemas) == 2


class TestExecuteTool:
    def test_unknown_tool_name_returns_not_found_without_raising(self) -> None:
        result = execute_tool("not_a_real_tool", {"name": "X"})
        assert json.loads(result) == {"found": False}

    def test_missing_name_argument_returns_not_found(self) -> None:
        result = execute_tool("lookup_organization", {})
        assert json.loads(result) == {"found": False}

    def test_blank_name_argument_returns_not_found(self) -> None:
        result = execute_tool("lookup_organization", {"name": "   "})
        assert json.loads(result) == {"found": False}

    @patch("metadata_enricher.llm.tools._ror_client")
    def test_affiliation_match_returns_canonical_name(self, mock_ror_client) -> None:
        mock_ror_client.search_affiliation.return_value = {
            "names": [{"value": "Universidad de Chile", "types": ["ror_display"]}]
        }

        result = execute_tool("lookup_organization", {"name": "U de Chile"})

        assert json.loads(result) == {"found": True, "canonical_name": "Universidad de Chile"}
        mock_ror_client.search_query.assert_not_called()

    @patch("metadata_enricher.llm.tools._ror_client")
    def test_falls_back_to_query_endpoint_when_affiliation_has_no_chosen_match(
        self, mock_ror_client
    ) -> None:
        mock_ror_client.search_affiliation.return_value = None
        mock_ror_client.search_query.return_value = [
            {"names": [{"value": "CONAF", "types": ["ror_display"]}]}
        ]

        result = execute_tool("lookup_organization", {"name": "CONAF"})

        assert json.loads(result) == {"found": True, "canonical_name": "CONAF"}
        mock_ror_client.search_query.assert_called_once_with("CONAF", limit=1)

    @patch("metadata_enricher.llm.tools._ror_client")
    def test_no_match_from_either_endpoint_returns_not_found(self, mock_ror_client) -> None:
        mock_ror_client.search_affiliation.return_value = None
        mock_ror_client.search_query.return_value = []

        result = execute_tool("lookup_organization", {"name": "Nonexistent Org"})

        assert json.loads(result) == {"found": False}

    @patch("metadata_enricher.llm.tools._ror_client")
    def test_ror_client_exception_returns_not_found_without_raising(
        self, mock_ror_client
    ) -> None:
        """A failed lookup must not crash the agent -- it's fed back to the
        model as a tool result, not surfaced as a pipeline error."""
        mock_ror_client.search_affiliation.side_effect = RuntimeError("network error")

        result = execute_tool("lookup_organization", {"name": "Some Org"})

        assert json.loads(result) == {"found": False}


class TestToolRegistry:
    def test_lookup_organization_registered(self) -> None:
        assert "lookup_organization" in TOOL_REGISTRY
