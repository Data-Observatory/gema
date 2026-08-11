#!/usr/bin/env python3
"""Generate minimal reverse-extracted inputs from a directory of ground-truth
metadata records, using scripts/reverse_input.py's corpus-agnostic extractor.

Two modes:
  1. Generate (default): read every ``*.json`` in --ground-truth-dir, write
     the minimal {url, title, description, publisher} input for each to
     --inputs-dir under the same filename. Add --fetch to also live-fetch
     each resource's URL and include the cleaned page text as
     fetched_content — the same field the real production pipeline reads
     (see reverse_input.py's ALLOWED_KEYS docstring for why this isn't a
     leak). Best-effort: a failed/empty fetch just omits the field.
  2. --self-check: don't generate — validate an existing --inputs-dir instead.
     Asserts no forbidden (enrichment-target) key ever leaked into a
     generated input, reports files where the Abstract-type description
     fallback was used, and (if --ground-truth-dir is also given) reports the
     identifier_type distribution of the sampled set as a sanity signal.

Usage:
    uv run python scripts/generate_inputs.py \
        --ground-truth-dir tests/fixtures/do_catalog/ground_truth \
        --inputs-dir tests/fixtures/do_catalog/inputs \
        --fetch

    uv run python scripts/generate_inputs.py --self-check \
        --inputs-dir tests/fixtures/do_catalog/inputs \
        --ground-truth-dir tests/fixtures/do_catalog/ground_truth
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from reverse_input import ALLOWED_KEYS, FORBIDDEN_KEYS, extract_minimal_input, select_description, unwrap_attributes


def generate(ground_truth_dir: Path, inputs_dir: Path, *, fetch: bool = False, fetch_delay: float = 0.5) -> int:
    inputs_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    fallback_files: list[str] = []
    fetch_ok = 0
    fetch_failed: list[str] = []

    for src in sorted(ground_truth_dir.glob("*.json")):
        raw = json.loads(src.read_text(encoding="utf-8"))
        attrs = unwrap_attributes(raw)

        fetched_content = None
        if fetch:
            from fetch_content import fetch_page_content  # noqa: PLC0415 — optional, network-dependent

            url = str((attrs.get("resource") or {}).get("identifier", ""))
            fetched_content = fetch_page_content(url)
            if fetched_content:
                fetch_ok += 1
            else:
                fetch_failed.append(src.name)
            time.sleep(fetch_delay)

        input_data = extract_minimal_input(attrs, fetched_content=fetched_content)
        _, used_fallback = select_description(attrs.get("descriptions") or [])
        if used_fallback:
            fallback_files.append(src.name)

        dest = inputs_dir / src.name
        dest.write_text(json.dumps(input_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1

    print(f"Generated {written} input(s) in {inputs_dir}/")
    if fetch:
        print(f"Live fetch: {fetch_ok}/{written} succeeded")
        if fetch_failed:
            print(f"  Failed/empty: {', '.join(fetch_failed)}")
    if fallback_files:
        print(f"\n⚠ {len(fallback_files)} file(s) had no Abstract-typed description (used descriptions[0]):")
        for f in fallback_files:
            print(f"  - {f}")
    return written


def _scan_forbidden(value: Any, path: str, violations: list[str]) -> None:
    """Recursively check that no FORBIDDEN_KEYS name appears as a dict key
    anywhere in *value* — defensive, since extract_minimal_input() only ever
    returns a flat {url, title, description, publisher} dict by construction,
    but this catches any future extension that might introduce nesting."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k in FORBIDDEN_KEYS:
                violations.append(f"{path}.{k}")
            _scan_forbidden(v, f"{path}.{k}", violations)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _scan_forbidden(item, f"{path}[{i}]", violations)


def self_check(inputs_dir: Path, ground_truth_dir: Path | None) -> int:
    """Returns 0 on success, 1 on any structural-leakage violation found."""
    input_files = sorted(inputs_dir.glob("*.json"))
    if not input_files:
        print(f"No input files found in {inputs_dir}/", file=sys.stderr)
        return 1

    violations: list[str] = []
    fallback_files: list[str] = []
    identifier_types: Counter[str] = Counter()

    for f in input_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        extra_keys = set(data.keys()) - ALLOWED_KEYS
        if extra_keys:
            violations.append(f"{f.name}: disallowed top-level key(s) {sorted(extra_keys)}")
        _scan_forbidden(data, f.name, violations)

        if ground_truth_dir is not None:
            gt_path = ground_truth_dir / f.name
            if gt_path.exists():
                gt_raw = json.loads(gt_path.read_text(encoding="utf-8"))
                gt_attrs = unwrap_attributes(gt_raw)
                _, used_fallback = select_description(gt_attrs.get("descriptions") or [])
                if used_fallback:
                    fallback_files.append(f.name)
                id_type = gt_attrs.get("resource", {}).get("identifier_type", "")
                identifier_types[str(id_type) or "(blank)"] += 1

    print(f"Checked {len(input_files)} input file(s) in {inputs_dir}/")

    if violations:
        print(f"\n❌ {len(violations)} structural-leakage violation(s):")
        for v in violations:
            print(f"  - {v}")
    else:
        print("✅ No forbidden keys found — every input stays within ALLOWED_KEYS.")

    if fallback_files:
        print(f"\n⚠ {len(fallback_files)} file(s) had no Abstract-typed description (used descriptions[0]):")
        for name in fallback_files:
            print(f"  - {name}")

    if identifier_types:
        print("\nGround-truth identifier_type distribution (sanity signal):")
        for id_type, count in identifier_types.most_common():
            print(f"  {id_type}: {count}")

    print(
        "\nNote: this catches structural leakage only (a wrong key present) — it "
        "cannot and does not try to catch semantic leakage where a description's "
        "prose happens to mention a creator/subject. That's an inherent property "
        "of real-world text, not a bug to chase."
    )

    return 1 if violations else 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ground-truth-dir", type=Path, help="Directory of ground-truth *.json files")
    parser.add_argument("--inputs-dir", type=Path, required=True, help="Directory to write/read minimal inputs")
    parser.add_argument("--self-check", action="store_true", help="Validate --inputs-dir instead of generating")
    parser.add_argument(
        "--fetch", action="store_true",
        help="Live-fetch each resource's URL to populate fetched_content (real network calls, best-effort)",
    )
    parser.add_argument("--fetch-delay", type=float, default=0.5, help="Seconds between fetches (default: 0.5)")
    args = parser.parse_args(argv)

    if args.self_check:
        sys.exit(self_check(args.inputs_dir, args.ground_truth_dir))

    if args.ground_truth_dir is None:
        print("--ground-truth-dir is required unless --self-check is passed.", file=sys.stderr)
        sys.exit(2)

    generate(args.ground_truth_dir, args.inputs_dir, fetch=args.fetch, fetch_delay=args.fetch_delay)


if __name__ == "__main__":
    main()
