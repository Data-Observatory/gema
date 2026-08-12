#!/usr/bin/env python3
"""Semi-automated ROR curation helper for do_catalog ground truth.

Source ground truth carries messy, unreliable org identifiers (raw
VIAF/Wikidata/malformed-ISNI entries — see BACKLOG.md's "Curated,
human-reviewed ROR/ISNI ground truth" item). This script does NOT fix
that data. It only queries ROR's public API for candidate matches
against each organization name that doesn't already carry a ROR
identifier, and writes a review file for a human to actually curate —
nothing here is auto-applied to any ground truth file.

Usage:
    uv run python scripts/curate_ror_isni.py \
        --ground-truth-dir tests/fixtures/do_catalog/ground_truth \
        --output reports/do_catalog/ror_isni_review.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from metadata_enricher.enrichers.ror_client import RORClient, get_display_name


def _add_identifier(
    identifiers_by_name: dict[str, dict[str, Any]], name: str, source_file: str
) -> dict[str, Any]:
    entry = identifiers_by_name.setdefault(
        name, {"org_name": name, "current_identifiers": [], "seen_in_files": []}
    )
    if source_file not in entry["seen_in_files"]:
        entry["seen_in_files"].append(source_file)
    return entry


def _record_identifier(entry: dict[str, Any], scheme: str, value: str) -> None:
    if not scheme or not value:
        return
    pair = {"scheme": scheme, "value": value}
    if pair not in entry["current_identifiers"]:
        entry["current_identifiers"].append(pair)


def collect_org_entries(ground_truth_dir: Path) -> dict[str, dict[str, Any]]:
    """Every organization name in *ground_truth_dir*, with whatever messy
    identifiers the source data already carries for it, keyed by name."""
    entries: dict[str, dict[str, Any]] = {}

    for path in sorted(ground_truth_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        stem = path.name

        for role in data.get("roles", []):
            if role.get("role_name_type") != "Organizational":
                continue
            name = role.get("role_name", "")
            if not name:
                continue
            entry = _add_identifier(entries, name, stem)
            for ni in role.get("name_identifiers", []):
                _record_identifier(
                    entry, ni.get("name_identifier_scheme", ""), ni.get("name_identifier", "")
                )
            for affil in role.get("affiliations", []):
                affil_name = affil.get("affiliation_name", "")
                if not affil_name:
                    continue
                affil_entry = _add_identifier(entries, affil_name, stem)
                _record_identifier(
                    affil_entry,
                    affil.get("affiliation_identifier_scheme", ""),
                    affil.get("affiliation_identifier", ""),
                )

        for pub in data.get("publishers", []):
            name = pub.get("publisher_name", "")
            if not name:
                continue
            entry = _add_identifier(entries, name, stem)
            _record_identifier(
                entry, pub.get("publisher_identifier_scheme", ""), pub.get("publisher_identifier", "")
            )

        for fr in data.get("funding_references", []):
            name = fr.get("funder_name", "")
            if not name:
                continue
            entry = _add_identifier(entries, name, stem)
            for fi in fr.get("funder_identifiers", []):
                _record_identifier(
                    entry, fi.get("funder_identifier_type", ""), fi.get("funder_identifier", "")
                )

    return entries


def needs_curation(entry: dict[str, Any]) -> bool:
    """True if this org has no ROR identifier among its current (messy) ones."""
    return not any(ident["scheme"] == "ROR" for ident in entry["current_identifiers"])


def find_ror_candidates(
    client: RORClient, name: str, *, delay_s: float = 0.2
) -> dict[str, Any]:
    """Query ROR for *name*. A ``chosen=True`` affiliation match is the
    strongest signal; otherwise return up to 3 query-endpoint alternatives
    for a human to pick from (or reject all of them)."""
    time.sleep(delay_s)  # be polite to the public API -- no client ID configured
    try:
        chosen = client.search_affiliation(name)
    except Exception as exc:
        return {"ror_candidate": None, "ror_alternatives": [], "lookup_error": str(exc)}
    if chosen is not None:
        return {
            "ror_candidate": {
                "ror_id": chosen.get("id", ""),
                "display_name": get_display_name(chosen),
                "match_type": "affiliation_chosen",
            },
            "ror_alternatives": [],
            "lookup_error": None,
        }

    try:
        candidates = client.search_query(name, limit=3)
    except Exception as exc:
        return {"ror_candidate": None, "ror_alternatives": [], "lookup_error": str(exc)}
    return {
        "ror_candidate": None,
        "ror_alternatives": [
            {"ror_id": c.get("id", ""), "display_name": get_display_name(c)} for c in candidates
        ],
        "lookup_error": None,
    }


def run(ground_truth_dir: Path, output_path: Path, limit: int | None = None) -> None:
    entries = collect_org_entries(ground_truth_dir)
    to_curate = [e for e in entries.values() if needs_curation(e)]
    if limit is not None:
        to_curate = to_curate[:limit]

    print(f"{len(entries)} unique org names, {len(to_curate)} without a ROR identifier already")

    with httpx.Client(timeout=30.0, follow_redirects=True) as http_client:
        client = RORClient(http_client=http_client)
        for i, entry in enumerate(to_curate, start=1):
            print(f"  [{i}/{len(to_curate)}] {entry['org_name'][:60]}...")
            entry.update(find_ror_candidates(client, entry["org_name"]))

    confident = sum(1 for e in to_curate if e.get("ror_candidate"))
    needs_review = sum(1 for e in to_curate if not e.get("ror_candidate") and e.get("ror_alternatives"))
    no_match = sum(
        1 for e in to_curate if not e.get("ror_candidate") and not e.get("ror_alternatives")
    )
    print(
        f"\n{confident} have a confident ROR match, {needs_review} have alternatives to review, "
        f"{no_match} had no ROR hit at all"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"organizations": to_curate}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nReview file written to {output_path} -- nothing here is auto-applied.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=None, help="Cap orgs queried (e.g. smoke test)")
    args = parser.parse_args()

    if not args.ground_truth_dir.is_dir():
        print(f"Not a directory: {args.ground_truth_dir}", file=sys.stderr)
        sys.exit(1)

    run(args.ground_truth_dir, args.output, args.limit)


if __name__ == "__main__":
    main()
