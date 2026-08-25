"""End-to-end pipeline wiring all components together."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from metadata_enricher.agents.registry import AgentRegistry, LLMClientFactory
from metadata_enricher.config.models import PipelineConfig
from metadata_enricher.enrichers.country_extractor import CountryExtractor
from metadata_enricher.input_sources.base import InputSource
from metadata_enricher.merger import MetadataMerger
from metadata_enricher.orchestrator import Orchestrator
from metadata_enricher.schemas import get_registry
from metadata_enricher.schemas.base import Schema, SchemaRegistry
from metadata_enricher.types import AgentResult, MetadataDocument, ResourceDescription, TokenUsage
from metadata_enricher.validation import PreFlightValidator

if TYPE_CHECKING:
    from metadata_enricher.enrichers.doi_resolver import DOIResolverEnricher
    from metadata_enricher.enrichers.identifier_enricher import IdentifierEnricher

logger = logging.getLogger(__name__)

# Same instance/behavior as agents/base.py's — reused here so identifier
# enrichment sees the same country hint the agents' own prompts were given.
_country_extractor = CountryExtractor()


class PipelineResult:
    """Result of processing a single resource."""

    def __init__(
        self,
        resource: ResourceDescription,
        document: MetadataDocument | None = None,
        error: str | None = None,
        source_path: str | None = None,
        warnings: list[str] | None = None,
        token_usage: TokenUsage | None = None,
        models_used: dict[str, str] | None = None,
    ) -> None:
        self.resource = resource
        self.document = document
        self.error = error
        self.source_path = source_path
        self.warnings = warnings or []
        self.token_usage = token_usage if token_usage is not None else TokenUsage()
        self.models_used = models_used or {}

    @property
    def success(self) -> bool:
        return self.error is None and self.document is not None


def _aggregate_token_usage(agent_results: list[AgentResult]) -> TokenUsage:
    """Sum token usage across agent_results, once per underlying LLM call.

    BaseAgent.run() attaches the *same* TokenUsage instance to every
    AgentResult it produces for a single call (one call -> N fields -> N
    AgentResults) — summing naively would multiply every agent's real cost
    by its field count. Dedup by object identity instead, which is exactly
    what's shared across those N results (confirmed: pydantic reuses the
    instance passed to a model field rather than copying it).
    """
    seen: set[int] = set()
    total = TokenUsage()
    for result in agent_results:
        usage = result.token_usage
        if id(usage) in seen:
            continue
        seen.add(id(usage))
        total = TokenUsage(
            prompt_tokens=total.prompt_tokens + usage.prompt_tokens,
            completion_tokens=total.completion_tokens + usage.completion_tokens,
            total_tokens=total.total_tokens + usage.total_tokens,
        )
    return total


def _build_models_used(agent_results: list[AgentResult], registry: AgentRegistry) -> dict[str, str]:
    """Map agent id -> the resolved model it actually ran with (e.g. what an
    OpenRouter "~...-latest" alias actually served), for display -- so a
    user relying on an auto-updating alias can confirm the real version.

    Skips an agent entirely when its TokenUsage carries no model (a mock/
    fake client, or a cache hit -- both already report zero usage for the
    same reason, see _aggregate_token_usage's docstring).
    """
    field_to_agent = {
        field_name: config.id
        for config in registry.get_agent_configs()
        for field_name in config.fields
    }
    models: dict[str, str] = {}
    seen: set[int] = set()
    for result in agent_results:
        agent_id = field_to_agent.get(result.field_name)
        if agent_id is None or id(result.token_usage) in seen:
            continue
        seen.add(id(result.token_usage))
        if result.token_usage.model:
            models[agent_id] = result.token_usage.model
    return models


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
        max_workers: int = 4,
        allow_partial: bool = False,
        identifier_enricher: IdentifierEnricher | None = None,
        doi_resolver: DOIResolverEnricher | None = None,
    ) -> None:
        self._config = config
        self._registry = schema_registry or get_registry()
        self._schema: Schema = self._registry.get(config.schema_name)
        self._llm_factory = llm_factory
        self._max_workers = max_workers
        self._allow_partial = allow_partial
        self._validator = PreFlightValidator(self._schema, self._registry)
        # Explicit injection (e.g. a fake in tests) always wins. Otherwise, build
        # the real ROR/ISNI/ORCID-backed enricher only if the config asks for it —
        # constructing it unconditionally would mean every Pipeline() call
        # touches the network-backed IdentifierResolver's clients.
        self._enricher = identifier_enricher
        if self._enricher is None and config.enable_identifier_enrichment:
            from metadata_enricher.enrichers.identifier_enricher import IdentifierEnricher
            from metadata_enricher.enrichers.identifier_resolver import IdentifierResolver

            self._enricher = IdentifierEnricher(IdentifierResolver())

        # Same explicit-injection-wins, opt-in-only-if-configured pattern as
        # the identifier enricher above.
        self._doi_resolver = doi_resolver
        if self._doi_resolver is None and config.enable_doi_resolution:
            from metadata_enricher.enrichers.crossref_client import CrossrefClient
            from metadata_enricher.enrichers.doi_resolver import DOIResolverEnricher

            self._doi_resolver = DOIResolverEnricher(CrossrefClient())

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
                        source_path=source_path,
                    )
                )
                continue

            # Auto-fetch page content (opt-in) BEFORE orchestration — agents read
            # resource.fetched_content synchronously while formatting their prompt,
            # so it must be populated before the orchestrator's wave executes.
            resource = self._maybe_fetch_content(resource)

            result = self._process_resource(resource)
            result.source_path = source_path
            results.append(result)

        return results

    def _maybe_fetch_content(self, resource: ResourceDescription) -> ResourceDescription:
        """Best-effort, opt-in auto-fetch of *resource.url*'s page text into
        ``resource.fetched_content``.

        Only fetches when all of the following hold:
        - ``config.enable_content_fetch`` is True (off by default — no
          behavior/cost/determinism change for existing users unless they
          explicitly opt in).
        - ``resource.fetched_content`` is empty/None — caller-supplied content
          is never overwritten; this stays a passthrough field by default.
        - ``resource.url`` is non-empty — nothing to fetch otherwise.

        A fetch failure (``fetch_page_content`` returns None on any error, by
        contract) is silently tolerated: resource processing continues with
        no ``fetched_content``, exactly as it does today. Wrapped in a
        try/except anyway — defense in depth, since this must never become a
        new way for a single resource's failure to abort the batch.
        """
        if not self._config.enable_content_fetch:
            return resource
        if resource.fetched_content or not resource.url:
            return resource
        try:
            from metadata_enricher.enrichers.content_fetcher import fetch_page_content

            content = fetch_page_content(resource.url)
        except Exception as exc:
            logger.warning("Content fetch failed for %s: %s", resource.url, exc)
            return resource
        if content:
            resource.fetched_content = content
        return resource

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
            orchestrator = Orchestrator(registry, max_workers=self._max_workers)
            agent_results = orchestrator.run(resource)
        except Exception as exc:
            logger.error("Orchestrator failed: %s", exc)
            return PipelineResult(resource=resource, error=f"Orchestration failed: {exc}")

        token_usage = _aggregate_token_usage(agent_results)
        models_used = _build_models_used(agent_results, registry)

        # Every agent errored (e.g. bad API key, unreachable provider) — this must
        # surface as a failure, not a "successful" empty document.
        if agent_results and all(r.error for r in agent_results):
            distinct_errors = sorted({r.error for r in agent_results if r.error})
            summary = "; ".join(distinct_errors[:3])
            logger.error("All agents failed for resource: %s", summary)
            return PipelineResult(
                resource=resource,
                error=f"All agents failed: {summary}",
                token_usage=token_usage,
                models_used=models_used,
            )

        # 4. Merge agent results into a MetadataDocument
        try:
            merger = MetadataMerger(self._schema)
            document = merger.merge(agent_results)
        except Exception as exc:
            logger.error("Merge failed: %s", exc)
            return PipelineResult(
                resource=resource,
                error=f"Merge failed: {exc}",
                token_usage=token_usage,
                models_used=models_used,
            )

        if not document.fields:
            logger.error("No fields extracted for resource — refusing to report success")
            return PipelineResult(
                resource=resource,
                error="No fields extracted — all agents returned empty results",
                token_usage=token_usage,
                models_used=models_used,
            )

        # Some (not all — that case returned earlier) agents failed. The resulting
        # document is missing whatever those agents were responsible for. Default
        # is to treat this as a failure too — a half-complete DataCite record
        # written to disk looks legitimate and could be published as-is. Callers
        # that want best-effort output anyway can opt in via allow_partial.
        failed = [r for r in agent_results if r.error]
        warnings: list[str] = []
        if failed:
            fields = sorted({r.field_name for r in failed})
            distinct_errors = sorted({r.error for r in failed if r.error})
            summary = "; ".join(distinct_errors[:3])
            if not self._allow_partial:
                logger.error("Partial agent failure for fields %s: %s", fields, summary)
                return PipelineResult(
                    resource=resource,
                    error=f"Fields failed: {', '.join(fields)} ({summary})",
                    token_usage=token_usage,
                    models_used=models_used,
                )
            warnings = [f"field '{r.field_name}' failed: {r.error}" for r in failed]
            logger.warning("Resource has incomplete fields (allow_partial): %s", summary)

        # 5. Post-merge DOI resolution (Crossref) -- runs before identifier
        # enrichment so backfilled creators/publishers still get a chance at
        # ROR/ISNI resolution below.
        if self._doi_resolver is not None:
            try:
                document = self._doi_resolver.enrich(document)
            except Exception as exc:
                logger.warning("DOI resolution failed: %s", exc)

        # 6. Post-merge identifier enrichment
        if self._enricher is not None:
            try:
                detected_country = _country_extractor.extract_country(
                    html_content=resource.fetched_content, url=resource.url
                )
                document = self._enricher.enrich(document, country=detected_country)
            except Exception as exc:
                logger.warning("Identifier enrichment failed: %s", exc)

        # 7. PID validation — every run, not just when explicitly requested.
        # Never blocks success: a bad/unresolvable PID becomes a warning, same
        # as an incomplete field. A registry being briefly unreachable must
        # not fail an otherwise-good resource.
        if self._config.validate_pids:
            try:
                from metadata_enricher.enrichers.pid_validator import validate_pids

                pid_checks = validate_pids(document.fields, resolve=self._config.validate_pids_live)
                warnings += [c.problem for c in pid_checks if c.problem is not None]
            except Exception as exc:
                logger.warning("PID validation failed: %s", exc)

        return PipelineResult(
            resource=resource,
            document=document,
            warnings=warnings,
            token_usage=token_usage,
            models_used=models_used,
        )
