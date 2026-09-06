"""Output writer for MetadataDocument to JSON file or stdout."""

from __future__ import annotations

import json
import logging
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

    def resolve_output_path(
        self,
        document: MetadataDocument,
        output_path: Path | None,
        filename_hint: str | None = None,
    ) -> Path | None:
        """Compute where write() would place *document*, without writing it.

        Same argument semantics as write() -- returns None for the stdout
        case (output_path is None). Exposed so callers that need to derive
        a *sibling* path (e.g. an alternate-format export next to the
        primary output) don't have to duplicate this filename logic.
        """
        if output_path is None:
            return None

        if not output_path.is_dir():
            return output_path

        if filename_hint:
            safe = "".join(c for c in filename_hint if c.isalnum() or c in "-_")[:80]
            filename = f"{safe or 'output'}.json"
        else:
            # schema:identifier is singular on a fully-merged document
            # (Open Question #23) -- a bare list is also tolerated
            # defensively.
            identifier = document.get_field("schema:identifier")
            candidates = (
                [identifier]
                if isinstance(identifier, dict)
                else (identifier if isinstance(identifier, list) else [])
            )
            doi = next(
                (
                    i.get("schema:value")
                    for i in candidates
                    if isinstance(i, dict)
                    and str(i.get("schema:propertyID", "")).upper() == "DOI"
                ),
                None,
            )
            name = document.get_field("schema:name")
            if doi:
                safe = str(doi).replace("/", "_").replace(":", "-")
                filename = f"{safe}.json"
            elif name:
                safe = (
                    "".join(c for c in str(name) if c.isalnum() or c in "-_")[:50] or "untitled"
                )
                filename = f"{safe}.json"
            else:
                filename = "output.json"
        return output_path / filename

    def write(
        self,
        document: MetadataDocument,
        output_path: Path | None = None,
        filename_hint: str | None = None,
    ) -> str:
        """Write document to file, directory, or stdout.

        Args:
            document: The MetadataDocument to write
            output_path:
                - None: print JSON to stdout, return the JSON string
                - File path: write JSON to that file
                - Directory path: write to <dir>/<name>.json
            filename_hint:
                When writing into a directory, use this (e.g. the input file's
                stem) as the filename instead of deriving one from the DOI/title.
                Prevents distinct resources with the same/missing title or DOI
                from silently overwriting each other.

        Returns:
            The JSON string that was written
        """
        json_str = self.format_json(document)

        if output_path is None:
            print(json_str)
            return json_str

        target = self.resolve_output_path(document, output_path, filename_hint)
        assert target is not None  # output_path is not None here

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json_str, encoding="utf-8")
        logger.info("Wrote output to %s", target)
        return json_str
