"""End-to-end pipeline wiring all components together."""

from __future__ import annotations

import logging

from metadata_enricher.agents.registry import AgentRegistry, LLMClientFactory
from metadata_enricher.config.models import PipelineConfig
from metadata_enricher.input_sources.base import InputSource
from metadata_enricher.merger import MetadataMerger
from metadata_enricher.orchestrator import Orchestrator
from metadata_enricher.schemas import get_registry
from metadata_enricher.schemas.base import Schema, SchemaRegistry
from metadata_enricher.types import MetadataDocument, ResourceDescription
from metadata_enricher.validation import PreFlightValidator

logger = logging.getLogger(__name__)


class PipelineResult:
    """Result of processing a single resource."""

    def __init__(
        self,
        resource: ResourceDescription,
        document: MetadataDocument | None = None,
        error: str | None = None,
    ) -> None:
        self.resource = resource
        self.document = document
        self.error = error

    @property
    def success(self) -> bool:
        return self.error is None and self.document is not None


class Pipeline:
    """End-to-end metadata enrichment pipeline.

    Wires together:
        InputSource -> PreFlightValidator -> AgentRegistry -> Orchestrator -> Merger

    Errors are isolated per resource so that a single failure never blocks
    the rest of the batch.
    """

    def __init__(
        self,
        config: PipelineConfig,
        schema_registry: SchemaRegistry | None = None,
        llm_factory: LLMClientFactory | None = None,
    ) -> None:
        self._config = config
        self._registry = schema_registry or get_registry()
        self._schema: Schema = self._registry.get(config.schema_name)
        self._llm_factory = llm_factory
        self._validator = PreFlightValidator(self._schema, self._registry)

    def run(self, input_source: InputSource, pattern: str = "*.json") -> list[PipelineResult]:
        """Run the full pipeline on all resources matching *pattern*.

        For each resource:
        1. Fetch resource data from the input source.
        2. Validate the resource (PreFlightValidator).
        3. Build an AgentRegistry from pipeline config.
        4. Execute the Orchestrator (parallel agents).
        5. Merge agent results into a MetadataDocument.

        Every resource is processed independently — a failure in one does
        not affect the others.
        """
        sources = input_source.list_sources(pattern)
        if not sources:
            logger.warning("No input sources found matching pattern '%s'", pattern)
            return []

        results: list[PipelineResult] = []

        for source_path in sources:
            logger.info("Processing: %s", source_path)
            try:
                resource = input_source.fetch(source_path)
            except Exception as exc:
                logger.error("Failed to fetch %s: %s", source_path, exc)
                results.append(
                    PipelineResult(
                        resource=ResourceDescription(),
                        error=f"Fetch failed: {exc}",
                    )
                )
                continue

            result = self._process_resource(resource)
            results.append(result)

        return results

    def _process_resource(self, resource: ResourceDescription) -> PipelineResult:
        """Process a single resource through the full pipeline."""
        # 1. Validate resource
        validation = self._validator.validate_resource(resource)
        if not validation.valid:
            errors_str = "; ".join(validation.errors)
            logger.warning("Resource failed validation: %s", errors_str)
            return PipelineResult(resource=resource, error=f"Validation failed: {errors_str}")

        # 2. Build agent registry
        try:
            registry = AgentRegistry(
                config=self._config,
                schema=self._schema,
                schema_registry=self._registry,
                llm_factory=self._llm_factory,
            )
        except Exception as exc:
            logger.error("Failed to build agent registry: %s", exc)
            return PipelineResult(resource=resource, error=f"Registry build failed: {exc}")

        # 3. Execute orchestrator (parallel agent waves)
        try:
            orchestrator = Orchestrator(registry)
            agent_results = orchestrator.run(resource)
        except Exception as exc:
            logger.error("Orchestrator failed: %s", exc)
            return PipelineResult(resource=resource, error=f"Orchestration failed: {exc}")

        # 4. Merge agent results into a MetadataDocument
        try:
            merger = MetadataMerger(self._schema)
            document = merger.merge(agent_results)
        except Exception as exc:
            logger.error("Merge failed: %s", exc)
            return PipelineResult(resource=resource, error=f"Merge failed: {exc}")

        return PipelineResult(resource=resource, document=document)
