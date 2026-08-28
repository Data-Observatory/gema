#!/usr/bin/env python3
"""Structural validator for do_catalog ground-truth records.

Nothing in the repo checks committed ground truth's *shape* today —
`gema validate` (src/metadata_enricher/cli.py) validates pipeline *inputs*,
and `scripts/validate_real_output.py` checks live pipeline *output* — neither
touches `tests/fixtures/do_catalog/ground_truth/`. This exists to catch the
exact bug class found and fixed in 3 files there (104.json/124.json/87.json):
an organization name sitting in `name_identifier` with the real identifier
value buried inside `scheme_uri`, instead of the canonical
name_identifier=<bare value>, scheme_uri=<fixed per-scheme constant> shape.

Usage:
    uv run python scripts/validate_ground_truth.py tests/fixtures/do_catalog/ground_truth
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Keys every do_catalog ground-truth file carries (confirmed across all 18
# committed pilot files) -- `funding_references`/`rights` are legitimately
# omitted on some records, not required.
REQUIRED_KEYS = frozenset({
    "alternate_identifiers", "audiences", "categories", "citations", "dates",
    "descriptions", "geo_locations", "languages", "media_files", "origin_name",
    "origin_priority", "publishers", "related_identifiers", "resource",
    "roles", "subjects", "temporal_events", "titles",
})

# Per-scheme value shape -- accepts either the bare form IdentifierEnricher
# emits or the URI-wrapped form some ground-truth entries use (both are
# legitimate corpus conventions; do_catalog_common.py's scheme-aware
# normalization already bridges them for scoring). What this rejects is free
# text (an organization name) standing in for the identifier value -- the
# actual corruption class this validator exists to catch.
_SCHEME_PATTERNS: dict[str, re.Pattern[str]] = {
    "ISNI": re.compile(r"^(https?://isni\.org/isni/)?[0-9]{15}[0-9Xx]$"),
    "ROR": re.compile(r"^https?://ror\.org/[a-z0-9]+/?$", re.IGNORECASE),
    "ORCID": re.compile(
        r"^(https?://orcid\.org/)?[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$", re.IGNORECASE
    ),
}

# A scheme_uri should be a fixed, generic scheme homepage -- never a
# record-specific URL. A run of 6+ digits is a strong signal an actual
# identifier value (e.g. an ISNI) got misplaced into this field instead.
_EMBEDDED_ID_RE = re.compile(r"\d{6,}")


class Violation:
    __slots__ = ("path", "message", "warning")

    def __init__(self, path: str, message: str, *, warning: bool = False) -> None:
        self.path = path
        self.message = message
        self.warning = warning

    def __str__(self) -> str:
        tag = "WARN" if self.warning else "FAIL"
        return f"[{tag}] {self.path}: {self.message}"


def _check_identifier(
    file_stem: str, location: str, value: str, scheme: str, scheme_uri: str
) -> list[Violation]:
    violations: list[Violation] = []
    if not value or not scheme:
        return violations
    pattern = _SCHEME_PATTERNS.get(scheme)
    if pattern and not pattern.match(value):
        violations.append(
            Violation(
                f"{file_stem}:{location}",
                f"scheme={scheme!r} but value {value!r} doesn't look like a "
                f"{scheme} identifier (swapped-field corruption?)",
            )
        )
    if scheme_uri and _EMBEDDED_ID_RE.search(scheme_uri) and pattern:
        violations.append(
            Violation(
                f"{file_stem}:{location}",
                f"scheme_uri {scheme_uri!r} contains an embedded identifier-like "
                "digit run -- should be a fixed generic scheme URI",
            )
        )
    return violations


def validate_record(file_stem: str, data: dict[str, Any]) -> list[Violation]:
    violations: list[Violation] = []

    missing = REQUIRED_KEYS - data.keys()
    if missing:
        violations.append(Violation(file_stem, f"missing required keys: {sorted(missing)}"))

    for i, role in enumerate(data.get("roles", [])):
        for j, nid in enumerate(role.get("name_identifiers", [])):
            violations.extend(
                _check_identifier(
                    file_stem,
                    f"roles[{i}].name_identifiers[{j}]",
                    nid.get("name_identifier", ""),
                    nid.get("name_identifier_scheme", ""),
                    nid.get("scheme_uri", ""),
                )
            )
        for j, aff in enumerate(role.get("affiliations", [])):
            violations.extend(
                _check_identifier(
                    file_stem,
                    f"roles[{i}].affiliations[{j}]",
                    aff.get("affiliation_identifier", ""),
                    aff.get("affiliation_identifier_scheme", ""),
                    aff.get("scheme_uri", ""),
                )
            )

    for i, pub in enumerate(data.get("publishers", [])):
        violations.extend(
            _check_identifier(
                file_stem,
                f"publishers[{i}]",
                pub.get("publisher_identifier", ""),
                pub.get("publisher_identifier_scheme", ""),
                pub.get("publisher_scheme_uri", ""),
            )
        )

    for i, rights in enumerate(data.get("rights", [])):
        rid = rights.get("rights_identifier", "")
        # Only Creative Commons SPDX ids are canonically all-uppercase
        # (CC-BY-4.0, CC0-1.0); ODbL-1.0/GFDL-1.3-or-later are legitimately
        # mixed-case per the SPDX license list, so they're excluded here to
        # avoid a false-positive warning on already-correct data.
        if rid.upper().startswith("CC") and rid != rid.upper():
            violations.append(
                Violation(
                    f"{file_stem}:rights[{i}]",
                    f"rights_identifier {rid!r} isn't canonically-cased SPDX "
                    f"(expected {rid.upper()!r})",
                    warning=True,
                )
            )

    return violations


def validate_dir(directory: Path) -> tuple[list[Violation], int]:
    all_violations: list[Violation] = []
    count = 0
    for path in sorted(directory.glob("*.json")):
        count += 1
        data = json.loads(path.read_text(encoding="utf-8"))
        all_violations.extend(validate_record(path.stem, data))
    return all_violations, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory of ground-truth JSON files")
    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"Not a directory: {args.directory}", file=sys.stderr)
        return 2

    violations, count = validate_dir(args.directory)
    for v in violations:
        print(v)

    failures = [v for v in violations if not v.warning]
    warnings = [v for v in violations if v.warning]
    print(f"\n{count} files checked, {len(failures)} failures, {len(warnings)} warnings")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
