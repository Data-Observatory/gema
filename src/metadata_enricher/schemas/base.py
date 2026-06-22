"""Schema abstraction for pluggable metadata schemas."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from metadata_enricher.types import AgentResult, MetadataDocument


@runtime_checkable
class Schema(Protocol):
    """Protocol defining the schema interface.

    Each schema implementation (DataCite 4.6, Dublin Core, etc.)
    must implement this interface.
    """

    @property
    def name(self) -> str:
        """Schema identifier (e.g., 'datacite-4.6')."""

    @property
    def version(self) -> str:
        """Schema version string."""

    @property
    def output_model(self) -> type[BaseModel]:
        """Pydantic model for validated output."""

    def validate_output(self, raw: dict[str, object]) -> BaseModel:
        """Validate a raw dict against the schema's output model."""

    def normalize_field(self, field_name: str, value: object) -> object:
        """Normalize a single field value (type coercion, cleanup)."""

    def merge_agent_results(self, results: list[AgentResult]) -> MetadataDocument:
        """Merge multiple agent outputs into a final metadata document."""

    def get_field_order(self) -> list[str]:
        """Field ordering for output serialization."""

    def get_required_fields(self) -> list[str]:
        """Minimum required fields for a valid document."""


class SchemaRegistry:
    """Registry for available metadata schemas."""

    def __init__(self) -> None:
        self._schemas: dict[str, Schema] = {}

    def register(self, schema: Schema) -> None:
        """Register a schema. Overwrites if name already exists."""
        self._schemas[schema.name] = schema

    def get(self, name: str) -> Schema:
        """Retrieve a schema by name. Raises KeyError if not found."""
        if name not in self._schemas:
            available = ", ".join(self._schemas.keys()) or "(none registered)"
            raise KeyError(f"Schema '{name}' not found. Available: {available}")
        return self._schemas[name]

    def list_schemas(self) -> list[str]:
        """List all registered schema names."""
        return list(self._schemas.keys())
