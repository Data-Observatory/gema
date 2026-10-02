"""Pre-flight validation for resources."""

from __future__ import annotations
import logging
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict
from metadata_enricher.types import ResourceDescription

logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    """Result of a validation check."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = []
    warnings: list[str] = []


class PreFlightValidator:
    """Validates resources before pipeline execution."""

    def validate_resource(self, resource: ResourceDescription) -> ValidationResult:
        """Check resource has minimum required fields for processing."""
        errors: list[str] = []
        warnings: list[str] = []

        # Must have at least a title or description or url
        has_content = any(
            [
                resource.title and resource.title.strip(),
                resource.description and resource.description.strip(),
                resource.url and resource.url.strip(),
            ]
        )
        if not has_content:
            errors.append("Resource must have at least a title, description, or url")

        # URL format validation if present
        if resource.url and resource.url.strip():
            try:
                parsed = urlparse(resource.url.strip())
                if parsed.scheme not in ("http", "https"):
                    warnings.append(f"URL scheme '{parsed.scheme}' is not http/https")
                if not parsed.netloc:
                    warnings.append("URL is missing network location")
            except Exception as e:
                warnings.append(f"URL parsing failed: {e}")

        # DOI format check if present
        if resource.doi and resource.doi.strip():
            doi = resource.doi.strip()
            if not (
                doi.startswith("10.")
                or doi.startswith("https://doi.org/10.")
                or doi.startswith("http://doi.org/10.")
            ):
                warnings.append(
                    f"DOI '{doi}' does not look like a standard DOI (expected 10.xxxx/... or https://doi.org/10.xxxx/...)"
                )

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
