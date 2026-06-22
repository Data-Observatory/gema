"""Thin merger that delegates to Schema for field-specific normalization."""

from __future__ import annotations

import logging

from metadata_enricher.schemas.base import Schema
from metadata_enricher.types import AgentResult, MetadataDocument

logger = logging.getLogger(__name__)


class MetadataMerger:
    """Merges AgentResults into a MetadataDocument using schema-driven normalization."""

    def __init__(self, schema: Schema) -> None:
        self._schema = schema

    @property
    def schema(self) -> Schema:
        return self._schema

    def merge(self, results: list[AgentResult]) -> MetadataDocument:
        """Merge agent results into a MetadataDocument.

        Delegates normalization and field ordering to the Schema.
        Validates that required fields are present.
        """
        if not results:
            return MetadataDocument(fields={})

        # Delegate merge logic to schema
        merged = self._schema.merge_agent_results(results)

        # If schema returns a MetadataDocument, use it directly
        if isinstance(merged, MetadataDocument):
            doc = merged
        else:
            # If schema returns a dict, wrap it
            doc = MetadataDocument(fields=dict(merged) if merged else {})

        # Validate required fields
        required = self._schema.get_required_fields()
        missing = []
        for req_field in required:
            value = doc.get_field(req_field)
            if value is None or (isinstance(value, (list, dict, str)) and len(value) == 0):
                missing.append(req_field)

        if missing:
            logger.warning("Missing required fields: %s", ", ".join(missing))

        return doc
