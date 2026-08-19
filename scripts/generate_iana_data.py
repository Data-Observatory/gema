#!/usr/bin/env python3
"""
Fetch IANA Media Types XML and generate src/metadata_enricher/data/iana_media_types.json.

Usage:
    python scripts/generate_iana_data.py

Output:
    src/metadata_enricher/data/iana_media_types.json with types and name_lookup dictionaries.
"""

from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone

IANA_URL = "https://www.iana.org/assignments/media-types/media-types.xml"
OUTPUT_PATH = "src/metadata_enricher/data/iana_media_types.json"
NS = {"ian": "http://www.iana.org/assignments"}


def fetch_xml(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "gema/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        content: bytes = resp.read()
        return content.decode("utf-8")


def parse_reference(record: ET.Element) -> str:
    """Extract a reference string from a record's xref elements."""
    xrefs = record.findall("ian:xref", NS)
    if not xrefs:
        return ""

    references = []
    for x in xrefs:
        ref_type = x.get("type", "")
        ref_data = x.get("data", "")
        text = (x.text or "").strip()

        if ref_type == "rfc":
            ref = ref_data.upper()
            if not ref.startswith("RFC"):
                ref = "RFC " + ref[3:]
            references.append(ref)
        elif ref_type == "person":
            references.append(ref_data.replace("_", " "))
        elif ref_type == "uri":
            references.append(text or ref_data)
        elif ref_type == "draft":
            references.append(ref_data.replace("RFC-", ""))
        elif ref_type == "rfc-errata":
            references.append(f"RFC Errata {ref_data}")
        elif ref_type == "registry":
            references.append(f"Registry: {ref_data}")
        else:
            references.append(text or ref_data)

    ref_str = "; ".join(references) if references else ""
    return ref_str.strip()


def deduplicate_name_lookup(types: dict[str, dict[str, str]]) -> dict[str, str]:
    """Build name_lookup keeping only short names that map to exactly one type."""
    name_to_types: dict[str, list[str]] = defaultdict(list)
    for full_type in types:
        if "/" in full_type:
            short = full_type.split("/", 1)[1].lower()
            name_to_types[short].append(full_type)

    lookup: dict[str, str] = {}
    for short_name, full_types in name_to_types.items():
        if len(full_types) == 1:
            lookup[short_name] = full_types[0]
    return lookup


def main() -> None:
    print(f"Fetching IANA media types from {IANA_URL}...")
    xml_content = fetch_xml(IANA_URL)

    print("Parsing XML...")
    root = ET.fromstring(xml_content)

    total_count = 0
    types: dict[str, dict[str, str]] = {}
    type_breakdown: dict[str, int] = defaultdict(int)

    for registry in root.findall("ian:registry", NS):
        registry_id = registry.get("id", "unknown")
        records = registry.findall("ian:record", NS)
        type_breakdown[registry_id] = 0

        for record in records:
            name_elem = record.find("ian:name", NS)
            if name_elem is None or not name_elem.text:
                continue
            subtype_name = name_elem.text.strip()

            template = None
            for file_elem in record.findall("ian:file", NS):
                if file_elem.get("type") == "template":
                    template = (file_elem.text or "").strip()
                    break

            if not template:
                template = f"{registry_id}/{subtype_name}"

            reference = parse_reference(record)

            types[template] = {
                "name": subtype_name,
                "template": template,
                "reference": reference,
            }
            total_count += 1
            type_breakdown[registry_id] += 1

    name_lookup = deduplicate_name_lookup(types)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output = {
        "_metadata": {
            "last_updated": now,
            "source": "IANA",
            "count": len(types),
        },
        "types": types,
        "name_lookup": name_lookup,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWritten {OUTPUT_PATH}")
    print(f"Total entries: {total_count}")
    print(f"Name lookups (unique short names): {len(name_lookup)}")
    print("\nBreakdown by top-level type:")
    for t, count in sorted(type_breakdown.items()):
        print(f"  {t}: {count}")


if __name__ == "__main__":
    main()
