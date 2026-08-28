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

Once a human has reviewed the output above and filled in ``approved_ror_id``/
``approved_isni_id``/``country`` on the entries they've decided on (both
start ``null`` — still nothing is auto-applied by the collection step
itself), promote those decisions into a durable
``config/overrides.yaml`` (see ``enrichers/identifier_overrides.py``) that
``IdentifierResolver`` checks before any network call:

    uv run python scripts/curate_ror_isni.py \
        --promote-from reports/do_catalog/ror_isni_review.json \
        --promote-to config/overrides.yaml

For a reviewer who'd rather work in a spreadsheet than hand-edit nested
JSON, flatten the review file to CSV, fill in the three decision columns
there, then promote straight from the CSV:

    uv run python scripts/curate_ror_isni.py \
        --promote-from reports/do_catalog/ror_isni_review.json \
        --to-csv reports/do_catalog/ror_isni_review.csv

    uv run python scripts/curate_ror_isni.py \
        --from-csv reports/do_catalog/ror_isni_review.csv \
        --promote-to config/overrides.yaml
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from metadata_enricher.enrichers.fuzzy_matcher import normalize_org_name
from metadata_enricher.enrichers.ror_client import RORClient, get_display_name


def _add_identifier(
    identifiers_by_name: dict[str, dict[str, Any]], name: str, source_file: str
) -> dict[str, Any]:
    entry = identifiers_by_name.setdefault(
        name,
        {
            "org_name": name,
            "current_identifiers": [],
            "seen_in_files": [],
            # Human-filled during review; both start null/unset. See
            # promote_to_overrides() -- an entry is only promoted once one
            # of these two is filled in. 'country' is optional, only needed
            # for a name that's genuinely ambiguous across countries.
            "approved_ror_id": None,
            "approved_isni_id": None,
            "country": None,
        },
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
            # A Personal creator's own name isn't an org name to curate --
            # but their affiliations ARE organizations, and skipping them
            # here (as this used to) dropped exactly the university/agency
            # names most needing ROR curation, since do_catalog's Personal
            # creators (rare, but real -- see BACKLOG.md) are the ones most
            # likely to carry an affiliation at all.
            if role.get("role_name_type") == "Organizational":
                name = role.get("role_name", "")
                if name:
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


def _load_overrides_entries(path: Path) -> list[dict[str, Any]]:
    """Existing entries in an overrides.yaml, or [] if it doesn't exist yet."""
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("overrides", []) if isinstance(raw, dict) else []
    return [e for e in entries if isinstance(e, dict)]


def _dedup_key(name: str, country: str | None) -> tuple[str, str | None]:
    # Must match IdentifierOverrides._load_entry's own normalization
    # (normalize_org_name + country.strip().upper()) exactly -- otherwise
    # two promote runs that differ only in raw casing (e.g. country "cl"
    # vs "CL") would write two YAML entries that collide silently at
    # load time instead of merging cleanly here.
    return (
        normalize_org_name(name),
        country.strip().upper() if country and country.strip() else None,
    )


def promote_entries(entries: list[dict[str, Any]], overrides_path: Path) -> int:
    """Promote human-approved entries (from either a review JSON's
    ``organizations`` list or a filled-in review CSV, both converge to this
    same shape) into overrides.yaml.

    An entry is promoted only when a human has filled in its
    ``approved_ror_id`` and/or ``approved_isni_id`` (both start ``null``/
    empty in a freshly generated review file) -- nothing here decides on its
    own which candidate is correct. Merges into *overrides_path* by
    ``(name, country)``, so re-running promotion after further review
    updates existing entries instead of duplicating them.

    Returns the number of entries promoted.
    """
    by_key = {
        _dedup_key(e.get("name", ""), e.get("country")): e
        for e in _load_overrides_entries(overrides_path)
    }

    promoted = 0
    for entry in entries:
        ror_id = entry.get("approved_ror_id")
        isni_id = entry.get("approved_isni_id")
        if not ror_id and not isni_id:
            continue
        name = entry["org_name"]
        country = entry.get("country") or None
        by_key[_dedup_key(name, country)] = {
            "name": name,
            "country": country,
            "ror_id": ror_id or None,
            "isni_id": isni_id or None,
        }
        promoted += 1

    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        yaml.safe_dump(
            {"overrides": list(by_key.values())}, allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    return promoted


def _load_review_entries(review_path: Path) -> list[dict[str, Any]]:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = review.get("organizations", [])
    return entries


def promote_to_overrides(review_path: Path, overrides_path: Path) -> int:
    """Promote human-approved entries from a review JSON file into
    overrides.yaml. See promote_entries() for the actual logic."""
    return promote_entries(_load_review_entries(review_path), overrides_path)


# One row per org: identifying/candidate info the reviewer needs to see,
# followed by the three decision columns they fill in -- same fields
# _add_identifier() seeds as null/[] in a freshly generated review file.
_CSV_FIELDS = [
    "org_name",
    "current_identifiers",
    "seen_in_files",
    "lookup_error",
    "ror_candidate_id",
    "ror_candidate_name",
    "ror_alt1_id",
    "ror_alt1_name",
    "ror_alt2_id",
    "ror_alt2_name",
    "ror_alt3_id",
    "ror_alt3_name",
    "approved_ror_id",
    "approved_isni_id",
    "country",
]


def review_to_csv(review_path: Path, csv_path: Path) -> int:
    """Flatten a review JSON's ``organizations`` list to one CSV row per
    org, for a reviewer who'd rather work in a spreadsheet than hand-edit
    nested JSON. Round-trips back via csv_to_review_entries()."""
    entries = _load_review_entries(review_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for entry in entries:
            candidate = entry.get("ror_candidate") or {}
            alternatives = entry.get("ror_alternatives") or []
            row = {
                "org_name": entry.get("org_name", ""),
                "current_identifiers": "; ".join(
                    f"{i['scheme']}:{i['value']}" for i in entry.get("current_identifiers", [])
                ),
                "seen_in_files": "; ".join(entry.get("seen_in_files", [])),
                "lookup_error": entry.get("lookup_error") or "",
                "ror_candidate_id": candidate.get("ror_id", ""),
                "ror_candidate_name": candidate.get("display_name", ""),
                "approved_ror_id": entry.get("approved_ror_id") or "",
                "approved_isni_id": entry.get("approved_isni_id") or "",
                "country": entry.get("country") or "",
            }
            for i in range(3):
                alt = alternatives[i] if i < len(alternatives) else {}
                row[f"ror_alt{i + 1}_id"] = alt.get("ror_id", "")
                row[f"ror_alt{i + 1}_name"] = alt.get("display_name", "")
            writer.writerow(row)
    return len(entries)


def csv_to_review_entries(csv_path: Path) -> list[dict[str, Any]]:
    """Read a filled-in review CSV back into the entry shape
    promote_entries() expects -- only the fields promotion actually reads
    (org_name, approved_ror_id, approved_isni_id, country) need to survive
    the round-trip; the rest of the CSV is reviewer-facing context only."""
    with csv_path.open(newline="", encoding="utf-8") as f:
        return [
            {
                "org_name": row.get("org_name", ""),
                "approved_ror_id": row.get("approved_ror_id") or None,
                "approved_isni_id": row.get("approved_isni_id") or None,
                "country": row.get("country") or None,
            }
            for row in csv.DictReader(f)
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=None, help="Cap orgs queried (e.g. smoke test)")
    parser.add_argument(
        "--promote-from", type=Path, help="Promote a reviewed review file instead of collecting"
    )
    parser.add_argument("--promote-to", type=Path, help="config/overrides.yaml to write/update")
    parser.add_argument(
        "--to-csv",
        type=Path,
        help="Flatten the --promote-from review JSON to this CSV path for spreadsheet review",
    )
    parser.add_argument(
        "--from-csv", type=Path, help="Promote decisions from a filled-in review CSV instead of JSON"
    )
    args = parser.parse_args()

    if args.to_csv is not None:
        if args.promote_from is None:
            print("--promote-from is required alongside --to-csv", file=sys.stderr)
            sys.exit(1)
        if not args.promote_from.is_file():
            print(f"Not a file: {args.promote_from}", file=sys.stderr)
            sys.exit(1)
        count = review_to_csv(args.promote_from, args.to_csv)
        print(f"Wrote {count} rows to {args.to_csv}")
        return

    if args.from_csv is not None:
        if args.promote_to is None:
            print("--promote-to is required alongside --from-csv", file=sys.stderr)
            sys.exit(1)
        if not args.from_csv.is_file():
            print(f"Not a file: {args.from_csv}", file=sys.stderr)
            sys.exit(1)
        count = promote_entries(csv_to_review_entries(args.from_csv), args.promote_to)
        print(f"Promoted {count} human-approved entries to {args.promote_to}")
        return

    if args.promote_from is not None:
        if args.promote_to is None:
            print("--promote-to is required alongside --promote-from", file=sys.stderr)
            sys.exit(1)
        if not args.promote_from.is_file():
            print(f"Not a file: {args.promote_from}", file=sys.stderr)
            sys.exit(1)
        count = promote_to_overrides(args.promote_from, args.promote_to)
        print(f"Promoted {count} human-approved entries to {args.promote_to}")
        return

    if args.ground_truth_dir is None or args.output is None:
        print(
            "--ground-truth-dir and --output are required (unless using --promote-from)",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.ground_truth_dir.is_dir():
        print(f"Not a directory: {args.ground_truth_dir}", file=sys.stderr)
        sys.exit(1)

    run(args.ground_truth_dir, args.output, args.limit)


if __name__ == "__main__":
    main()
