"""Tests for pre-flight validation (metadata_enricher.validation)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from metadata_enricher.types import ResourceDescription
from metadata_enricher.validation import PreFlightValidator, ValidationResult


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
        result = PreFlightValidator().validate_resource(resource)
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_empty_resource_fails(self):
        """Empty resource (no url, title, or description) fails."""
        resource = ResourceDescription()
        result = PreFlightValidator().validate_resource(resource)
        assert result.valid is False
        assert any(word in result.errors[0].lower() for word in ("title", "description", "url"))

    def test_invalid_url_scheme_warns(self):
        """URL with non-http/https scheme emits a warning but is valid."""
        resource = ResourceDescription(url="ftp://example.com")
        result = PreFlightValidator().validate_resource(resource)
        assert result.valid is True
        assert any("scheme" in w for w in result.warnings)

    def test_missing_netloc_warns(self):
        """URL without network location emits a warning but is valid."""
        resource = ResourceDescription(url="not-a-url")
        result = PreFlightValidator().validate_resource(resource)
        assert result.valid is True
        assert any("network location" in w for w in result.warnings)

    def test_valid_doi_no_warning(self):
        """Valid DOI format (10.xxxx/...) produces no DOI warning."""
        resource = ResourceDescription(
            url="https://example.com",
            doi="10.1234/foo",
        )
        result = PreFlightValidator().validate_resource(resource)
        assert result.valid is True
        assert not any("DOI" in w for w in result.warnings)

    def test_invalid_doi_warns(self):
        """Non-standard DOI format emits a DOI warning."""
        resource = ResourceDescription(
            url="https://example.com",
            doi="xyz123",
        )
        result = PreFlightValidator().validate_resource(resource)
        assert result.valid is True
        assert any("DOI" in w for w in result.warnings)
