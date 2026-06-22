"""Tests for pre-flight validation (metadata_enricher.validation)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from metadata_enricher.config.models import AgentConfig, PipelineConfig, ProviderConfig
from metadata_enricher.schemas.base import SchemaRegistry
from metadata_enricher.types import AgentResult, MetadataDocument, ResourceDescription
from metadata_enricher.validation import PreFlightValidator, ValidationResult


class _MockSchema:
    """Minimal schema satisfying the Schema protocol for PreFlightValidator tests."""

    @property
    def name(self) -> str:
        return "datacite-4.6"

    @property
    def version(self) -> str:
        return "4.6"

    @property
    def output_model(self) -> type[BaseModel]:
        return BaseModel

    def validate_output(self, raw: dict[str, object]) -> BaseModel:
        return BaseModel()

    def normalize_field(self, field_name: str, value: object) -> object:
        return value

    def merge_agent_results(self, results: list[AgentResult]) -> MetadataDocument:
        return MetadataDocument()

    def get_field_order(self) -> list[str]:
        return []

    def get_required_fields(self) -> list[str]:
        return []


def make_valid_config() -> PipelineConfig:
    """Build a valid PipelineConfig for testing."""
    return PipelineConfig(
        schema_name="datacite-4.6",
        agents=[
            AgentConfig(
                id="a1",
                name="Agent 1",
                fields=["titles"],
                prompt="test",
                provider="p1",
            ),
        ],
        providers=[
            ProviderConfig(name="p1", base_url="http://localhost", api_key_env="KEY"),
        ],
        default_provider="p1",
    )


class TestValidationResult:
    """ValidationResult: outcome of a validation check."""

    def test_default_valid_true(self):
        """Minimal creation: valid=True, empty errors and warnings."""
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_with_errors(self):
        """Errors list is preserved."""
        result = ValidationResult(valid=False, errors=["something went wrong"])
        assert result.valid is False
        assert result.errors == ["something went wrong"]

    def test_with_warnings(self):
        """Warnings list is preserved."""
        result = ValidationResult(valid=True, warnings=["check this"])
        assert result.valid is True
        assert result.warnings == ["check this"]

    def test_extra_fields_forbidden(self):
        """extra='forbid' — unknown fields raise."""
        with pytest.raises(ValidationError):
            ValidationResult(valid=True, extra_field="bad")


class TestPreFlightValidatorValidateResource:
    """PreFlightValidator.validate_resource — resource-level checks."""

    def test_valid_resource_passes(self):
        """Resource with url, title, and description is valid."""
        resource = ResourceDescription(
            url="https://example.com",
            title="Test Title",
            description="A description",
        )
        result = PreFlightValidator(schema=_MockSchema()).validate_resource(resource)
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_empty_resource_fails(self):
        """Empty resource (no url, title, or description) fails."""
        resource = ResourceDescription()
        result = PreFlightValidator(schema=_MockSchema()).validate_resource(resource)
        assert result.valid is False
        assert any(word in result.errors[0].lower() for word in ("title", "description", "url"))

    def test_invalid_url_scheme_warns(self):
        """URL with non-http/https scheme emits a warning but is valid."""
        resource = ResourceDescription(url="ftp://example.com")
        result = PreFlightValidator(schema=_MockSchema()).validate_resource(resource)
        assert result.valid is True
        assert any("scheme" in w for w in result.warnings)

    def test_missing_netloc_warns(self):
        """URL without network location emits a warning but is valid."""
        resource = ResourceDescription(url="not-a-url")
        result = PreFlightValidator(schema=_MockSchema()).validate_resource(resource)
        assert result.valid is True
        assert any("network location" in w for w in result.warnings)

    def test_valid_doi_no_warning(self):
        """Valid DOI format (10.xxxx/...) produces no DOI warning."""
        resource = ResourceDescription(
            url="https://example.com",
            doi="10.1234/foo",
        )
        result = PreFlightValidator(schema=_MockSchema()).validate_resource(resource)
        assert result.valid is True
        assert not any("DOI" in w for w in result.warnings)

    def test_invalid_doi_warns(self):
        """Non-standard DOI format emits a DOI warning."""
        resource = ResourceDescription(
            url="https://example.com",
            doi="xyz123",
        )
        result = PreFlightValidator(schema=_MockSchema()).validate_resource(resource)
        assert result.valid is True
        assert any("DOI" in w for w in result.warnings)


class TestPreFlightValidatorValidateConfig:
    """PreFlightValidator.validate_config — pipeline config checks."""

    def test_valid_config_passes(self):
        """Valid PipelineConfig passes validation."""
        registry = SchemaRegistry()
        registry.register(_MockSchema())
        config = make_valid_config()
        result = PreFlightValidator(schema=_MockSchema(), registry=registry).validate_config(config)
        assert result.valid is True
        assert result.errors == []

    def test_config_unknown_provider_fails(self):
        """Agent referencing a provider not in the providers list fails."""
        config = PipelineConfig.model_construct(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig.model_construct(
                    id="a1",
                    name="A1",
                    fields=["titles"],
                    prompt="test",
                    provider="unknown",
                ),
            ],
            providers=[
                ProviderConfig.model_construct(
                    name="p1", base_url="http://localhost", api_key_env="KEY"
                ),
            ],
            default_provider="p1",
        )
        result = PreFlightValidator(schema=_MockSchema()).validate_config(config)
        assert result.valid is False
        assert any("unknown" in e for e in result.errors)

    def test_config_self_dependency_fails(self):
        """Agent that depends on itself fails."""
        config = PipelineConfig.model_construct(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig.model_construct(
                    id="a1",
                    name="A1",
                    fields=["titles"],
                    prompt="test",
                    provider="p1",
                    depends_on=["a1"],
                ),
            ],
            providers=[
                ProviderConfig.model_construct(
                    name="p1", base_url="http://localhost", api_key_env="KEY"
                ),
            ],
        )
        result = PreFlightValidator(schema=_MockSchema()).validate_config(config)
        assert result.valid is False
        assert any("depends on itself" in e for e in result.errors)

    def test_config_unknown_dependency_fails(self):
        """Agent depending on a non-existent agent ID fails."""
        config = PipelineConfig.model_construct(
            schema_name="datacite-4.6",
            agents=[
                AgentConfig.model_construct(
                    id="a1",
                    name="A1",
                    fields=["titles"],
                    prompt="test",
                    provider="p1",
                ),
                AgentConfig.model_construct(
                    id="a2",
                    name="A2",
                    fields=["titles"],
                    prompt="test",
                    provider="p1",
                    depends_on=["nonexistent"],
                ),
            ],
            providers=[
                ProviderConfig.model_construct(
                    name="p1", base_url="http://localhost", api_key_env="KEY"
                ),
            ],
        )
        result = PreFlightValidator(schema=_MockSchema()).validate_config(config)
        assert result.valid is False
        assert any("nonexistent" in e for e in result.errors)
