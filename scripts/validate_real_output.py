#!/usr/bin/env python3
"""Real-world output validator — checks the pipeline actually produces usable metadata.

This is deliberately NOT the golden/regression suite (tests/test_regression.py,
which replays cached LLM responses so it never touches a real API) and NOT the
semantic scorer (scripts/run_live_eval.py, which asks an LLM judge how good the
metadata "feels" compared to a reference). This script runs the real pipeline
against a real input with live LLM calls and asks a narrower, harder question:
would a human reviewer accept this record before publishing it?

Checks performed on the live output:
    1. The pipeline produced valid, parseable JSON.
    2. Structural completeness: titles, creators, dates, descriptions,
       resource block are present and non-placeholder.
    3. Abstract: at least one Abstract-type description, substantive length,
       not a verbatim copy of the title.
    4. Subjects and topics/categories: present, non-blank.
    5. Every PID found in the output (DOI, ROR, ISNI) matches the identifier
       scheme's real format. Unless --no-resolve is passed, each PID is also
       looked up against its real registry (doi.org / ror.org / isni.org) to
       confirm it actually resolves, not just that it looks right.

Usage:
    uv run python scripts/validate_real_output.py
    uv run python scripts/validate_real_output.py --input examples/sample_input02.json
    uv run python scripts/validate_real_output.py --input-dir tests/fixtures/geoportal/inputs --limit 5
    uv run python scripts/validate_real_output.py --no-resolve --no-enrich
    uv run python scripts/validate_real_output.py --output-dir reports/real_validation/outputs

Exit codes:
    0 = every input passed with no FAIL checks (WARN is still a pass)
    1 = at least one FAIL check anywhere
    2 = environment not configured (missing API key) or no input files found
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from metadata_enricher.enrichers.pid_validator import PidCheck, validate_pids

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = Path("config/agents.yaml")
DEFAULT_INPUT = Path("examples/sample_input01.json")
DEFAULT_SCHEMA = "datacite-4.6"

Status = Literal["PASS", "WARN", "FAIL"]

# Minimum length (chars) for an abstract to count as real content rather than
# a stub like "N/A" or a one-word placeholder.
MIN_ABSTRACT_LEN = 30

PLACEHOLDER_TOKENS = {"todo", "tbd", "n/a", "na", "xxx", "string", "null", "none", "unknown"}


@dataclass
class Check:
    name: str
    status: Status
    detail: str


@dataclass
class InputReport:
    stem: str
    checks: list[Check] = field(default_factory=list)
    pids: list[PidCheck] = field(default_factory=list)
    output_json: str | None = None
    pipeline_error: str | None = None

    @property
    def worst_status(self) -> Status:
        if self.pipeline_error:
            return "FAIL"
        statuses = [c.status for c in self.checks]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        return "PASS"


# ── Content checks ───────────────────────────────────────────────────────────


def _is_placeholder(text: str) -> bool:
    return text.strip().lower() in PLACEHOLDER_TOKENS


def check_structure(output: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []

    titles = output.get("titles") or []
    names = [t.get("name", "") for t in titles if isinstance(t, dict)]
    names = [n for n in names if n and not _is_placeholder(n)]
    if names:
        checks.append(Check("titles", "PASS", f"{len(names)} title(s), e.g. {names[0]!r}"))
    else:
        checks.append(Check("titles", "FAIL", "no non-placeholder title found"))

    creators = output.get("creators") or []
    creator_names = [
        c.get("creator_name", "") for c in creators if isinstance(c, dict) and c.get("creator_name")
    ]
    if creator_names:
        checks.append(Check("creators", "PASS", f"{len(creator_names)} creator(s)"))
    else:
        checks.append(Check("creators", "WARN", "no creators extracted"))

    dates = output.get("dates") or []
    if dates:
        checks.append(Check("dates", "PASS", f"{len(dates)} date(s)"))
    else:
        checks.append(Check("dates", "WARN", "no dates extracted"))

    resource = output.get("resource") or {}
    rtype = str(resource.get("resource_type", ""))
    year = str(resource.get("publication_year", ""))
    if rtype:
        checks.append(Check("resource.resource_type", "PASS", rtype))
    else:
        checks.append(Check("resource.resource_type", "WARN", "empty resource_type"))
    if re.match(r"^(19|20)\d{2}$", year):
        checks.append(Check("resource.publication_year", "PASS", year))
    elif year:
        checks.append(Check("resource.publication_year", "WARN", f"implausible year: {year!r}"))
    else:
        checks.append(Check("resource.publication_year", "WARN", "empty publication_year"))

    return checks


def check_abstract(output: dict[str, Any]) -> Check:
    descriptions = output.get("descriptions") or []
    titles = {t.get("name", "").strip().lower() for t in output.get("titles") or [] if isinstance(t, dict)}

    abstracts = [
        d.get("description", "").strip()
        for d in descriptions
        if isinstance(d, dict) and str(d.get("description_type", "")).lower() == "abstract"
    ]
    abstracts = [a for a in abstracts if a and not _is_placeholder(a)]

    if not abstracts:
        return Check("abstract", "FAIL", "no Abstract-type description found")

    best = max(abstracts, key=len)
    if len(best) < MIN_ABSTRACT_LEN:
        return Check("abstract", "FAIL", f"abstract too short ({len(best)} chars): {best!r}")
    if best.strip().lower() in titles:
        return Check("abstract", "WARN", "abstract is a verbatim copy of the title")
    return Check("abstract", "PASS", f"{len(best)} chars: {best[:80]!r}...")


def check_subjects_topics(output: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []

    subjects = output.get("subjects") or []
    subj_names = [
        s.get("subject_name", "") for s in subjects if isinstance(s, dict) and s.get("subject_name")
    ]
    subj_names = [s for s in subj_names if not _is_placeholder(s)]
    if subj_names:
        checks.append(Check("subjects", "PASS", f"{len(subj_names)}: {subj_names[:5]}"))
    else:
        checks.append(Check("subjects", "WARN", "no subjects extracted"))

    categories = output.get("categories") or []
    cat_names = [
        c.get("name", "") for c in categories if isinstance(c, dict) and c.get("name")
    ]
    cat_names = [c for c in cat_names if not _is_placeholder(c)]
    if cat_names:
        checks.append(Check("topics/categories", "PASS", f"{len(cat_names)}: {cat_names[:5]}"))
    else:
        checks.append(Check("topics/categories", "WARN", "no categories extracted"))

    return checks


def pid_checks_to_report_checks(pid_checks: list[PidCheck]) -> list[Check]:
    """Translate the shared validator's PidChecks into this script's report Checks.

    ORCID PIDs never appear here — see ``pid_validator.validate_pids``'s docstring
    for why ORCID has no equivalent "does this resolve" registry check.
    """
    if not pid_checks:
        return [Check("pids", "WARN", "no DOI/ROR/ISNI identifiers found anywhere in output")]

    checks: list[Check] = []
    for pc in pid_checks:
        if pc.problem is not None:
            checks.append(Check(f"pid:{pc.scheme}", "FAIL", pc.problem))
        elif pc.resolved is True:
            checks.append(Check(f"pid:{pc.scheme}", "PASS", f"{pc.value!r} resolves ({pc.location})"))
        else:
            checks.append(Check(f"pid:{pc.scheme}", "PASS", f"well-formed: {pc.value!r} ({pc.location})"))
    return checks


# ── Pipeline execution ────────────────────────────────────────────────────────


def _check_api_key(config: Any) -> None:
    from metadata_enricher.config.models import PipelineConfig

    assert isinstance(config, PipelineConfig)
    provider = None
    if config.default_provider:
        provider = next((p for p in config.providers if p.name == config.default_provider), None)
    if provider is None:
        provider = next((p for p in config.providers if p.default), config.providers[0])

    if not os.environ.get(provider.api_key_env):
        print(
            f"ERROR: Environment variable '{provider.api_key_env}' is not set "
            f"(required by default provider '{provider.name}').",
            file=sys.stderr,
        )
        sys.exit(2)


def run_pipeline_on(
    input_path: Path,
    config_path: Path,
    schema_name: str,
    enrich: bool,
    fresh_cache: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run the real pipeline on one input file. Returns (output_dict, error)."""
    from metadata_enricher.config.loader import load_config
    from metadata_enricher.input_sources.filesystem import FilesystemInputSource
    from metadata_enricher.llm.factory import reset_client_cache
    from metadata_enricher.output import OutputWriter
    from metadata_enricher.pipeline import Pipeline
    from metadata_enricher.schemas import get_registry

    config = load_config(config_path)
    config.enable_identifier_enrichment = enrich

    reset_client_cache()

    def _run(cache_dir: Path | None) -> tuple[dict[str, Any] | None, str | None]:
        llm_factory = None
        if cache_dir is not None:
            from metadata_enricher.agents.registry import LLMClientFactory  # noqa: F401
            from metadata_enricher.config.models import ProviderConfig
            from metadata_enricher.llm.base import LLMClient
            from metadata_enricher.llm.factory import create_llm_client

            def llm_factory(
                provider: ProviderConfig,
                model: str,
                temperature: float = 0.0,
                max_tokens: int | None = None,
            ) -> LLMClient:
                return create_llm_client(
                    provider, model=model, temperature=temperature, max_tokens=max_tokens,
                    cache_dir=cache_dir,
                )

        pipeline = Pipeline(config=config, llm_factory=llm_factory, max_workers=config.max_workers)
        results = pipeline.run(FilesystemInputSource(), pattern=str(input_path))
        if not results:
            return None, "no pipeline results (input did not match any file)"
        result = results[0]
        if not result.success or result.document is None:
            return None, result.error or "unknown pipeline failure"

        schema = get_registry().get(schema_name)
        json_str = OutputWriter(schema).format_json(result.document)
        return json.loads(json_str), None

    if fresh_cache:
        with tempfile.TemporaryDirectory(prefix="metagen_validate_real_") as tmpdir:
            return _run(Path(tmpdir) / "cache")
    return _run(None)


# ── Reporting ─────────────────────────────────────────────────────────────────


def _print_report(report: InputReport) -> None:
    print(f"\n=== {report.stem} — {report.worst_status} ===")
    if report.pipeline_error:
        print(f"  PIPELINE ERROR: {report.pipeline_error}")
        return
    for c in report.checks:
        marker = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}[c.status]
        print(f"  {marker} {c.status:<4} {c.name:<24} {c.detail}")


def _write_markdown_report(reports: list[InputReport], report_path: Path) -> None:
    lines = [f"# Real Output Validation — {datetime.now().isoformat(timespec='seconds')}", ""]
    overall = "PASS" if all(r.worst_status != "FAIL" for r in reports) else "FAIL"
    lines.append(f"**Overall:** {overall}  ")
    lines.append(f"**Inputs evaluated:** {len(reports)}")
    lines.append("")
    for r in reports:
        lines.append(f"## {r.stem} — {r.worst_status}")
        lines.append("")
        if r.pipeline_error:
            lines.append(f"**Pipeline error:** {r.pipeline_error}")
            lines.append("")
            continue
        lines.append("| Check | Status | Detail |")
        lines.append("|---|---|---|")
        for c in r.checks:
            detail = c.detail.replace("|", "\\|")
            lines.append(f"| {c.name} | {c.status} | {detail} |")
        lines.append("")
        if r.pids:
            lines.append("### PIDs found")
            lines.append("")
            lines.append("| Scheme | Value | Location | Format OK | Resolved |")
            lines.append("|---|---|---|---|---|")
            for p in r.pids:
                resolved_str = "—" if p.resolved is None else ("yes" if p.resolved else "no")
                lines.append(
                    f"| {p.scheme} | {p.value} | {p.location} | "
                    f"{'yes' if p.format_ok else 'no'} | {resolved_str} |"
                )
            lines.append("")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--input", type=Path, help="Single input JSON file to validate")
    group.add_argument(
        "--input-dir", type=Path, help="Directory of input JSON files to validate (see --limit)"
    )
    parser.add_argument(
        "--limit", type=int, default=3,
        help="Max files to process when --input-dir is a directory (default: 3)",
    )
    parser.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG, help="Pipeline config YAML")
    parser.add_argument("-s", "--schema", default=DEFAULT_SCHEMA, help="Schema name")
    parser.add_argument(
        "--no-enrich", action="store_true",
        help="Disable ROR/ISNI identifier enrichment (default: use config's setting)",
    )
    parser.add_argument(
        "--no-resolve", action="store_true",
        help="Skip live PID resolution against doi.org/ror.org/isni.org — format check only",
    )
    parser.add_argument(
        "--fresh-cache", action="store_true",
        help="Bypass the on-disk LLM cache — force real API calls for every agent",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="If set, write each input's raw pipeline output JSON to this directory",
    )
    parser.add_argument(
        "--reports-dir", type=Path, default=Path("reports/real_validation"),
        help="Directory for the Markdown report (default: reports/real_validation)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    from dotenv import load_dotenv

    load_dotenv()
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    from metadata_enricher.config.loader import load_config

    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"ERROR: failed to load config {args.config}: {exc}", file=sys.stderr)
        sys.exit(2)
    _check_api_key(config)

    if args.input_dir:
        if not args.input_dir.is_dir():
            print(f"ERROR: not a directory: {args.input_dir}", file=sys.stderr)
            sys.exit(2)
        input_files = sorted(args.input_dir.glob("*.json"))[: args.limit]
    else:
        input_files = [args.input or DEFAULT_INPUT]

    input_files = [f for f in input_files if f.exists()]
    if not input_files:
        print("ERROR: no input files found.", file=sys.stderr)
        sys.exit(2)

    enrich = not args.no_enrich
    http_client = None if args.no_resolve else httpx.Client(headers={"User-Agent": "metagen-validate-real/0.1"})

    reports: list[InputReport] = []
    try:
        for input_file in input_files:
            print(f"Processing {input_file.name} (live pipeline call, enrich={enrich})...", file=sys.stderr)
            output, error = run_pipeline_on(
                input_file, args.config, args.schema, enrich, args.fresh_cache
            )
            report = InputReport(stem=input_file.stem, pipeline_error=error)
            if output is not None:
                report.output_json = json.dumps(output, ensure_ascii=False, indent=2)
                report.checks.append(Check("json_validity", "PASS", "output parses as valid JSON"))
                report.checks.extend(check_structure(output))
                report.checks.append(check_abstract(output))
                report.checks.extend(check_subjects_topics(output))
                pid_checks = validate_pids(output, resolve=http_client is not None, client=http_client)
                report.checks.extend(pid_checks_to_report_checks(pid_checks))
                report.pids = pid_checks

                if args.output_dir:
                    args.output_dir.mkdir(parents=True, exist_ok=True)
                    (args.output_dir / f"{input_file.stem}.json").write_text(
                        report.output_json, encoding="utf-8"
                    )
            reports.append(report)
            _print_report(report)
    finally:
        if http_client is not None:
            http_client.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = args.reports_dir / f"validation_{timestamp}.md"
    _write_markdown_report(reports, report_path)
    print(f"\nReport written to {report_path}", file=sys.stderr)

    fail_count = sum(1 for r in reports if r.worst_status == "FAIL")
    print(
        f"\n{len(reports) - fail_count}/{len(reports)} input(s) passed with no FAIL checks.",
        file=sys.stderr,
    )
    sys.exit(1 if fail_count else 0)


if __name__ == "__main__":
    main()
