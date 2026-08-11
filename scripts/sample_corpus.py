#!/usr/bin/env python3
"""Sample a working subset from the do-catalog-resources S3 corpus for eval.

Two source presets (see SOURCE_PRESETS):
  - "main":  s3://do-catalog-resources/final_resources/YYYY=2026/{MM=04,MM=06}/
             source=Data Observatory/priority=1/  — the general eval corpus.
             Stratified by month, seeded, reproducible. A pilot subset (per
             --pilot-size) is a strict subset of the full draw (same seed),
             not a separately-drawn sample.
  - "orcid": s3://do-catalog-resources/final_resources/YYYY=2026/MM=04/
             source=DataCite/  — sampled specifically for Personal creators
             (needed to exercise the ORCID-matching path at all: this pool is
             confirmed to have those in abundance, unlike "main" which has
             essentially none — see the plan doc for the full investigation).
             Not split into pilot/full; the whole slice is committed.

Uses the AWS CLI (`aws s3api` / `aws s3 cp`) via subprocess with profile
`catalogo-admin` — no boto3 dependency.

Usage:
    uv run python scripts/sample_corpus.py --source-prefix main --target 100 --pilot-size 18 --seed 42
    uv run python scripts/sample_corpus.py --source-prefix orcid --target 20 --seed 42
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BUCKET = "do-catalog-resources"
AWS_PROFILE = "catalogo-admin"

# (month_label, s3_prefix) pairs per preset. "main" spans two months; "orcid"
# has no MM=06 equivalent (confirmed empirically — do not assume one exists).
SOURCE_PRESETS: dict[str, list[tuple[str, str]]] = {
    "main": [
        ("04", "final_resources/YYYY=2026/MM=04/source=Data Observatory/priority=1/"),
        ("06", "final_resources/YYYY=2026/MM=06/source=Data Observatory/priority=1/"),
    ],
    "orcid": [
        ("04", "final_resources/YYYY=2026/MM=04/source=DataCite/"),
    ],
}

MAIN_GROUND_TRUTH_PILOT_DIR = Path("tests/fixtures/do_catalog/ground_truth")
MAIN_GROUND_TRUTH_FULL_DIR = Path("data/do_catalog/ground_truth")
MAIN_MANIFEST_PATH = Path("tests/fixtures/do_catalog/manifest.json")

ORCID_GROUND_TRUTH_DIR = Path("tests/fixtures/do_catalog_orcid/ground_truth")
ORCID_MANIFEST_PATH = Path("tests/fixtures/do_catalog_orcid/manifest.json")


# ---------------------------------------------------------------------------
# S3 access (subprocess — no boto3)
# ---------------------------------------------------------------------------

def _run_aws(args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["aws", *args, "--profile", AWS_PROFILE],
        capture_output=True, timeout=timeout, check=False,
    )


def list_prefix(prefix: str) -> list[dict[str, Any]]:
    """List real (non-zero-byte, non-directory-marker) objects under *prefix*.

    A zero-byte placeholder object has been confirmed present at least once in
    this bucket (the MM=06 priority=1 prefix) — filtered out here, not left
    for callers to trip over.
    """
    result = _run_aws(["s3api", "list-objects-v2", "--bucket", BUCKET, "--prefix", prefix, "--output", "json"])
    if result.returncode != 0:
        msg = f"aws s3api list-objects-v2 failed for {prefix!r}: {result.stderr.decode(errors='replace')}"
        raise RuntimeError(msg)
    data = json.loads(result.stdout or b"{}")
    contents: list[dict[str, Any]] = data.get("Contents", [])
    return [c for c in contents if c.get("Size", 0) > 0]


def download(key: str, *, retries: int = 1) -> bytes | None:
    """Download an object's content. Retries once by default, then gives up
    (caller is responsible for redrawing a replacement — see sample_main)."""
    for attempt in range(retries + 1):
        result = _run_aws(["s3", "cp", f"s3://{BUCKET}/{key}", "-"], timeout=30.0)
        if result.returncode == 0 and result.stdout:
            return result.stdout
        logger.warning("download attempt %d/%d failed for %s", attempt + 1, retries + 1, key)
    return None


# ---------------------------------------------------------------------------
# Filename parsing — "<id>. <title>.json" (Data Observatory) or "<id>.json"
# (DataCite, no title at all) — both handled by stripping ".json" first,
# then matching the leading (possibly hierarchical, e.g. "2.10") numeric id.
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s*(.*)$")


def parse_id_title(basename: str) -> tuple[str, str] | None:
    if not basename.endswith(".json"):
        return None
    stem = basename[:-len(".json")]
    m = _ID_RE.match(stem)
    if not m:
        return None
    return m.group(1), m.group(2)


# ---------------------------------------------------------------------------
# Collision resolution — bare id -> month-tag -> trailing letter, applied
# only over the drawn sample (never the full pool).
# ---------------------------------------------------------------------------

def resolve_collisions(entries: list[dict[str, Any]]) -> None:
    """Mutates each entry in place, setting entry["final_filename"]."""
    by_id: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        by_id.setdefault(e["id_token"], []).append(e)

    for id_token, group in by_id.items():
        if len(group) == 1:
            group[0]["final_filename"] = f"{id_token}.json"
            continue
        by_month: dict[str, list[dict[str, Any]]] = {}
        for e in group:
            by_month.setdefault(e["month"], []).append(e)
        for month, month_group in by_month.items():
            if len(month_group) == 1:
                month_group[0]["final_filename"] = f"{id_token}_MM{month}.json"
            else:
                for i, e in enumerate(sorted(month_group, key=lambda x: x["s3_key"])):
                    e["final_filename"] = f"{id_token}_MM{month}{chr(97 + i)}.json"


# ---------------------------------------------------------------------------
# "main" preset — stratified by month, pilot subset is a strict subset
# ---------------------------------------------------------------------------

def sample_main(target: int, pilot_size: int, seed: int) -> None:
    rng = random.Random(seed)
    sampled_at = _timestamp()

    strata: dict[str, list[dict[str, Any]]] = {}
    for month, prefix in SOURCE_PRESETS["main"]:
        pool: list[dict[str, Any]] = []
        for obj in list_prefix(prefix):
            key = obj["Key"]
            parsed = parse_id_title(key.rsplit("/", 1)[-1])
            if parsed is None:
                logger.warning("Skipping unparseable filename: %s", key)
                continue
            id_token, title = parsed
            pool.append({
                "s3_key": key, "month": month, "id_token": id_token,
                "original_title": title, "priority": 1, "source": "Data Observatory",
            })
        pool.sort(key=lambda e: e["s3_key"])  # deterministic before rng.sample
        strata[month] = pool
        logger.info("month %s: %d real objects", month, len(pool))

    total_pool = sum(len(p) for p in strata.values())
    if target > total_pool:
        logger.warning("target %d exceeds pool size %d — clamping", target, total_pool)
        target = total_pool

    # Proportional per-stratum allocation, largest-remainder to hit `target` exactly.
    month_targets = _proportional_allocation(
        {m: len(p) for m, p in strata.items()}, target
    )
    pilot_targets = _proportional_allocation(month_targets, min(pilot_size, target))

    all_entries: list[dict[str, Any]] = []
    for month, pool in strata.items():
        k = month_targets[month]
        drawn = rng.sample(pool, k)
        pilot_k = pilot_targets[month]
        for i, entry in enumerate(drawn):
            entry["pilot"] = i < pilot_k  # first pilot_k of this stratum's draw
        all_entries.extend(drawn)

    resolve_collisions(all_entries)

    MAIN_GROUND_TRUTH_PILOT_DIR.mkdir(parents=True, exist_ok=True)
    MAIN_GROUND_TRUTH_FULL_DIR.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    for i, entry in enumerate(all_entries):
        content = _download_with_redraw(entry, strata[entry["month"]], all_entries)
        if content is None:
            logger.error("Giving up on %s after retries+redraw exhausted", entry["s3_key"])
            continue

        dest = MAIN_GROUND_TRUTH_FULL_DIR / entry["final_filename"]
        dest.write_bytes(content)
        if entry["pilot"]:
            (MAIN_GROUND_TRUTH_PILOT_DIR / entry["final_filename"]).write_bytes(content)

        manifest.append({
            "id_token": entry["id_token"],
            "final_filename": entry["final_filename"],
            "s3_key": entry["s3_key"],
            "month": entry["month"],
            "priority": entry["priority"],
            "source": entry["source"],
            "original_title": entry["original_title"],
            "sha256": hashlib.sha256(content).hexdigest(),
            "pilot": entry["pilot"],
            "seed": seed,
            "sampled_at": sampled_at,
        })
        logger.info("[%d/%d] %s -> %s (pilot=%s)", i + 1, len(all_entries),
                     entry["s3_key"], entry["final_filename"], entry["pilot"])

    MAIN_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MAIN_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    n_pilot = sum(1 for m in manifest if m["pilot"])
    print(f"main: {len(manifest)} files sampled ({n_pilot} pilot). Manifest: {MAIN_MANIFEST_PATH}")


def _download_with_redraw(
    entry: dict[str, Any], stratum_pool: list[dict[str, Any]], drawn_so_far: list[dict[str, Any]],
    max_redraws: int = 3,
) -> bytes | None:
    """Download *entry*; on failure, redraw a replacement from the same
    stratum (excluding already-drawn keys) up to *max_redraws* times, mutating
    *entry* in place to the replacement so the manifest reflects what was
    actually fetched, not the original failed pick."""
    content = download(entry["s3_key"])
    if content is not None:
        return content

    drawn_keys = {e["s3_key"] for e in drawn_so_far}
    candidates = [c for c in stratum_pool if c["s3_key"] not in drawn_keys]
    for _ in range(max_redraws):
        if not candidates:
            return None
        replacement = candidates.pop(random.randrange(len(candidates)))
        content = download(replacement["s3_key"])
        if content is not None:
            logger.warning("Redrew %s -> %s after download failure", entry["s3_key"], replacement["s3_key"])
            entry["s3_key"] = replacement["s3_key"]
            entry["id_token"] = replacement["id_token"]
            entry["original_title"] = replacement["original_title"]
            entry["final_filename"] = f"{replacement['id_token']}.json"
            drawn_keys.add(replacement["s3_key"])
            return content
        drawn_keys.add(replacement["s3_key"])
    return None


def _proportional_allocation(sizes: dict[str, int], target: int) -> dict[str, int]:
    """Largest-remainder apportionment of *target* across strata weighted by
    *sizes*, guaranteeing the allocations sum to exactly *target* (capped at
    each stratum's own size)."""
    total = sum(sizes.values())
    if total == 0:
        return {k: 0 for k in sizes}

    raw = {k: (target * v) / total for k, v in sizes.items()}
    base = {k: min(int(v), sizes[k]) for k, v in raw.items()}
    remaining = target - sum(base.values())

    remainders = sorted(raw.items(), key=lambda kv: kv[1] - int(kv[1]), reverse=True)
    for k, _ in remainders:
        if remaining <= 0:
            break
        if base[k] < sizes[k]:
            base[k] += 1
            remaining -= 1
    return base


# ---------------------------------------------------------------------------
# "orcid" preset — sample until *target* Personal-creator files are found
# ---------------------------------------------------------------------------

def sample_orcid(target: int, seed: int) -> None:
    rng = random.Random(seed)
    sampled_at = _timestamp()

    pool: list[dict[str, Any]] = []
    for month, prefix in SOURCE_PRESETS["orcid"]:
        for obj in list_prefix(prefix):
            key = obj["Key"]
            parsed = parse_id_title(key.rsplit("/", 1)[-1])
            if parsed is None:
                logger.warning("Skipping unparseable filename: %s", key)
                continue
            id_token, title = parsed
            pool.append({
                "s3_key": key, "month": month, "id_token": id_token,
                "original_title": title, "priority": None, "source": "DataCite",
            })

    pool.sort(key=lambda e: e["s3_key"])
    rng.shuffle(pool)
    logger.info("orcid pool: %d real objects, drawing in shuffled order until %d qualify",
                len(pool), target)

    qualifying: list[dict[str, Any]] = []
    checked = 0
    for entry in pool:
        if len(qualifying) >= target:
            break
        checked += 1
        content = download(entry["s3_key"])
        if content is None:
            logger.warning("download failed, skipping %s", entry["s3_key"])
            continue
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("invalid JSON, skipping %s", entry["s3_key"])
            continue
        name_types = [
            r.get("role_name_type") for r in data.get("roles", []) if r.get("type") == "Creator"
        ]
        if "Personal" not in name_types:
            continue
        entry["content"] = content
        qualifying.append(entry)

    logger.info("Found %d/%d qualifying (Personal creator) files after checking %d",
                len(qualifying), target, checked)
    if len(qualifying) < target:
        logger.warning("Could not reach target=%d — only %d qualifying files found in the pool",
                        target, len(qualifying))

    resolve_collisions(qualifying)

    ORCID_GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for entry in qualifying:
        content = entry.pop("content")
        dest = ORCID_GROUND_TRUTH_DIR / entry["final_filename"]
        dest.write_bytes(content)
        manifest.append({
            "id_token": entry["id_token"],
            "final_filename": entry["final_filename"],
            "s3_key": entry["s3_key"],
            "month": entry["month"],
            "priority": entry["priority"],
            "source": entry["source"],
            "original_title": entry["original_title"],
            "sha256": hashlib.sha256(content).hexdigest(),
            "pilot": True,  # the whole slice is committed outright, not pilot/full-split
            "seed": seed,
            "sampled_at": sampled_at,
        })

    ORCID_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ORCID_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"orcid: {len(manifest)} files sampled. Manifest: {ORCID_MANIFEST_PATH}")


def _timestamp() -> str:
    # Not Date.now()/argless-new-Date() in a Workflow script — this is a plain
    # CLI script, real wall-clock time is exactly what belongs in the manifest.
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-prefix", choices=sorted(SOURCE_PRESETS), required=True)
    parser.add_argument("--target", type=int, default=100, help="Total files to sample (default: 100)")
    parser.add_argument("--pilot-size", type=int, default=18,
                         help="[main only] Pilot subset size, a strict subset of --target (default: 18)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S",
    )

    if args.source_prefix == "main":
        sample_main(args.target, args.pilot_size, args.seed)
    else:
        sample_orcid(args.target, args.seed)


if __name__ == "__main__":
    main()
