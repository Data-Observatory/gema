"""Output writer for MetadataDocument to JSON file or stdout."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from metadata_enricher.schemas.base import Schema
from metadata_enricher.types import MetadataDocument

logger = logging.getLogger(__name__)


class OutputWriter:
    """Writes MetadataDocument as JSON to file or stdout with schema-driven field ordering."""

    def __init__(self, schema: Schema) -> None:
        self._schema = schema

    def format_json(self, document: MetadataDocument) -> str:
        """Format document as JSON string with schema field ordering.

        Fields in schema.get_field_order() appear first (in order).
        Remaining fields follow alphabetically.
        """
        field_order = self._schema.get_field_order()
        ordered: dict[str, object] = {}
        for field_name in field_order:
            value = document.get_field(field_name)
            if value is not None:
                ordered[field_name] = value
        for key in sorted(document.fields.keys()):
            if key not in ordered:
                ordered[key] = document.fields[key]
        return json.dumps(ordered, indent=2, ensure_ascii=False, default=str)

    def write(self, document: MetadataDocument, output_path: Path | None = None) -> str:
        """Write document to file, directory, or stdout.

        Args:
            document: The MetadataDocument to write
            output_path:
                - None: print JSON to stdout, return the JSON string
                - File path: write JSON to that file
                - Directory path: write to <dir>/<resource_id>.json based on DOI or title

        Returns:
            The JSON string that was written
        """
        json_str = self.format_json(document)

        if output_path is None:
            print(json_str)
            return json_str

        if output_path.is_dir():
            doi = document.get_field("doi") or document.get_field("identifiers")
            title = document.get_field("titles")
            if doi:
                safe = str(doi).replace("/", "_").replace(":", "-")
                filename = f"{safe}.json"
            elif title:
                title_str = (
                    title[0].get("title", "untitled")
                    if isinstance(title, list) and title
                    else "untitled"
                )
                safe = "".join(c for c in title_str if c.isalnum() or c in "-_")[:50] or "untitled"
                filename = f"{safe}.json"
            else:
                filename = "output.json"
            target = output_path / filename
        else:
            target = output_path

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json_str, encoding="utf-8")
        logger.info("Wrote output to %s", target)
        return json_str
