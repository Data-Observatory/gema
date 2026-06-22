"""Input source abstraction for reading metadata resources."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from metadata_enricher.types import ResourceDescription


@runtime_checkable
class InputSource(Protocol):
    """Protocol for reading metadata resources from various sources.

    Implementations support filesystem files, URLs, APIs, etc.
    """

    def fetch(self, source: str) -> ResourceDescription:
        """Fetch a single resource from a source identifier (path, URL, etc.).

        Args:
            source: Identifier for the resource to fetch.

        Returns:
            A populated ResourceDescription.

        Raises:
            FileNotFoundError: If the source does not exist.
            ValueError: If the source content is malformed.
        """

    def list_sources(self, pattern: str) -> list[str]:
        """List available source identifiers matching a pattern.

        Args:
            pattern: A pattern to match (e.g., directory path, glob, file path).

        Returns:
            Sorted list of matching source identifiers.
        """
