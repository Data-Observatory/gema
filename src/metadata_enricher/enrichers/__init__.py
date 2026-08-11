"""Deterministic post-merge enrichment modules."""

from metadata_enricher.enrichers.content_fetcher import fetch_page_content
from metadata_enricher.enrichers.identifier_enricher import IdentifierEnricher
from metadata_enricher.enrichers.identifier_resolver import IdentifierResolver
from metadata_enricher.enrichers.identifier_types import IdentifierMatch

__all__ = [
    "IdentifierEnricher",
    "IdentifierMatch",
    "IdentifierResolver",
    "fetch_page_content",
]
