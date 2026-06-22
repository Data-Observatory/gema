"""Filesystem-based input source implementation."""

from __future__ import annotations

import json
import os
import glob as glob_module

from metadata_enricher.types import ResourceDescription


class FilesystemInputSource:
    """Reads metadata resources from the local filesystem.

    Supports single JSON files, directories (scans for .json files),
    and glob patterns.
    """

    def fetch(self, source: str) -> ResourceDescription:
        """Read a JSON file and parse it into a ResourceDescription.

        Args:
            source: Path to a JSON file on the filesystem.

        Returns:
            A populated ResourceDescription.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file content is not valid JSON.
        """
        if not os.path.isfile(source):
            raise FileNotFoundError(f"Input file not found: {source}")

        try:
            with open(source, encoding="utf-8") as f:
                data: dict = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in input file '{source}': {e}") from e

        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a JSON object (dict) in '{source}', got {type(data).__name__}"
            )

        return ResourceDescription(**data)

    def list_sources(self, pattern: str) -> list[str]:
        """List available JSON files matching the given pattern.

        Supported pattern types:
        - Directory path: returns all .json files in that directory (non-recursive)
        - Glob pattern: returns files matching the glob
        - Single file path: returns [pattern] if file exists, else []
        - Nonexistent path: returns []

        Args:
            pattern: Directory path, glob pattern, or file path.

        Returns:
            Sorted list of matching file paths.
        """
        if os.path.isdir(pattern):
            entries: list[str] = [
                os.path.join(pattern, f) for f in sorted(os.listdir(pattern)) if f.endswith(".json")
            ]
            return entries

        if os.path.isfile(pattern):
            return [pattern]

        matched = sorted(glob_module.glob(pattern))
        if matched:
            return matched

        return []
