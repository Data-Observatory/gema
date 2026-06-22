"""Pre-flight validation for resources and pipeline configs."""

from __future__ import annotations
import logging
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict
from metadata_enricher.schemas.base import Schema, SchemaRegistry
from metadata_enricher.types import ResourceDescription
from metadata_enricher.config.models import PipelineConfig

logger = logging.getLogger(__name__)


class ValidationResult(BaseModel):
    """Result of a validation check."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = []
    warnings: list[str] = []


class PreFlightValidator:
    """Validates resources and configs before pipeline execution."""

    def __init__(self, schema: Schema, registry: SchemaRegistry | None = None) -> None:
        self._schema = schema
        self._registry = registry

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

    def validate_config(self, config: PipelineConfig) -> ValidationResult:
        """Check config is valid for pipeline execution."""
        errors: list[str] = []
        warnings: list[str] = []

        # Check schema_name exists in registry if registry provided
        if self._registry is not None:
            available = self._registry.list_schemas()
            if config.schema_name not in available:
                errors.append(
                    f"Schema '{config.schema_name}' not found. Available: {', '.join(available) if available else '(none)'}"
                )

        # Check provider references are valid (cross-ref validation already in PipelineConfig, but double-check)
        provider_names = {p.name for p in config.providers}
        for agent in config.agents:
            if agent.provider not in provider_names:
                errors.append(f"Agent '{agent.id}' references unknown provider '{agent.provider}'")

        # Check for depends_on cycle (simple check: agent can't depend on itself)
        agent_ids = {a.id for a in config.agents}
        for agent in config.agents:
            for dep in agent.depends_on:
                if dep == agent.id:
                    errors.append(f"Agent '{agent.id}' depends on itself")
                if dep not in agent_ids:
                    errors.append(f"Agent '{agent.id}' depends on unknown agent '{dep}'")

        # Check at least one agent exists (PipelineConfig already enforces min_length=1, but be explicit)
        if len(config.agents) == 0:
            errors.append("Config must define at least one agent")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
