"""Tests for Schema Registry (metadata_enricher.schemas.base)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from metadata_enricher.schemas.base import Schema, SchemaRegistry
from metadata_enricher.types import AgentResult, MetadataDocument


class _FakeOutput(BaseModel):
    """Concrete model for FakeSchema to avoid Pydantic v2 BaseModel() error."""


class FakeSchema:
    """Minimal schema implementation that satisfies the Schema protocol for testing."""

    @property
    def name(self) -> str:
        return "fake-1.0"

    @property
    def version(self) -> str:
        return "1.0"

    @property
    def output_model(self) -> type[BaseModel]:
        return _FakeOutput

    def build_output_model(self, fields: list[str]) -> type[BaseModel]:
        return _FakeOutput

    def validate_output(self, raw: dict) -> BaseModel:
        return _FakeOutput()

    def normalize_field(self, field_name: str, value: object) -> object:
        return value

    def merge_agent_results(self, results: list[AgentResult]) -> MetadataDocument:
        return MetadataDocument()

    def get_field_order(self) -> list[str]:
        return ["title", "description"]

    def get_required_fields(self) -> list[str]:
        return ["title"]


class AnotherFakeSchema:
    """Second fake schema to test multiple registrations."""

    @property
    def name(self) -> str:
        return "another-2.0"

    @property
    def version(self) -> str:
        return "2.0"

    @property
    def output_model(self) -> type[BaseModel]:
        return _FakeOutput

    def build_output_model(self, fields: list[str]) -> type[BaseModel]:
        return _FakeOutput

    def validate_output(self, raw: dict) -> BaseModel:
        return _FakeOutput()

    def normalize_field(self, field_name: str, value: object) -> object:
        return value

    def merge_agent_results(self, results: list[AgentResult]) -> MetadataDocument:
        return MetadataDocument()

    def get_field_order(self) -> list[str]:
        return []

    def get_required_fields(self) -> list[str]:
        return []


class TestSchemaRegistry:
    """SchemaRegistry: registration, retrieval, and listing."""

    def test_empty_registry(self):
        """New registry has no schemas."""
        registry = SchemaRegistry()
        assert registry.list_schemas() == []

    def test_register_schema(self):
        """Register stores a schema."""
        registry = SchemaRegistry()
        schema = FakeSchema()
        registry.register(schema)
        assert registry.list_schemas() == ["fake-1.0"]

    def test_list_schemas(self):
        """list_schemas returns all registered names."""
        registry = SchemaRegistry()
        registry.register(FakeSchema())
        registry.register(AnotherFakeSchema())
        names = registry.list_schemas()
        assert "fake-1.0" in names
        assert "another-2.0" in names
        assert len(names) == 2

    def test_get_schema(self):
        """get returns the registered schema instance."""
        registry = SchemaRegistry()
        schema = FakeSchema()
        registry.register(schema)
        retrieved = registry.get("fake-1.0")
        assert retrieved is schema
        assert retrieved.name == "fake-1.0"
        assert retrieved.version == "1.0"

    def test_get_nonexistent_raises_key_error(self):
        """get with unknown name raises KeyError with available schemas."""
        registry = SchemaRegistry()
        with pytest.raises(KeyError) as exc_info:
            registry.get("nonexistent")
        message = str(exc_info.value)
        assert "nonexistent" in message
        assert "none registered" in message

    def test_get_nonexistent_with_registered_schemas(self):
        """KeyError message lists available schemas when some exist."""
        registry = SchemaRegistry()
        registry.register(FakeSchema())
        with pytest.raises(KeyError) as exc_info:
            registry.get("bad-name")
        message = str(exc_info.value)
        assert "bad-name" in message
        assert "fake-1.0" in message

    def test_register_overwrites_duplicate_name(self):
        """Registering with same name overwrites the previous schema."""
        registry = SchemaRegistry()
        schema1 = FakeSchema()
        schema2 = FakeSchema()
        registry.register(schema1)
        registry.register(schema2)
        # Should have overwritten — get returns the latest
        assert registry.list_schemas() == ["fake-1.0"]
        assert registry.get("fake-1.0") is schema2

    def test_schema_methods_callable_through_registry(self):
        """All FakeSchema methods work when accessed via registry.get()."""
        registry = SchemaRegistry()
        registry.register(FakeSchema())
        schema = registry.get("fake-1.0")

        # All methods should be callable without error
        assert schema.name == "fake-1.0"
        assert schema.version == "1.0"
        assert issubclass(schema.output_model, BaseModel)
        assert isinstance(schema.validate_output({"key": "val"}), BaseModel)
        assert schema.normalize_field("title", "hello") == "hello"
        assert isinstance(
            schema.merge_agent_results([AgentResult(field_name="x", value="y")]), MetadataDocument
        )
        assert schema.get_field_order() == ["title", "description"]
        assert schema.get_required_fields() == ["title"]

    def test_schema_is_runtime_checkable(self):
        """Schema protocol is runtime_checkable — isinstance works."""
        registry = SchemaRegistry()
        schema = FakeSchema()
        registry.register(schema)
        retrieved = registry.get("fake-1.0")
        assert isinstance(retrieved, Schema)
