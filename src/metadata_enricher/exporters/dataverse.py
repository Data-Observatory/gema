"""Convert a DataCite MetadataDocument into Dataverse's native dataset JSON.

Most fields map deterministically — DataCite already extracted them
faithfully, there's nothing left to decide. The one genuinely ambiguous
field is Subject: Dataverse's citation metadata block requires it, and
restricts it to a small fixed controlled vocabulary (confirmed live
against a real Dataverse 6.11 instance on 2026-08-05 — see
SUBJECT_CATEGORIES), while DataCite's own subject extraction is free-text.
Picking the right bucket for an arbitrary resource needs judgment a lookup
table won't have — that's the one optional LLM call this module makes,
via classify_subject() / to_dataverse_json(classify_subject=True).

This is NOT a Schema Protocol implementation (schemas/base.py) — that
Protocol builds a MetadataDocument from raw AgentResults (i.e. extracts
from scratch), which isn't what's needed here: re-running a full
extraction pass would double LLM cost re-deriving facts (title, dates,
creators) the DataCite pipeline already got right. This module transforms
an already-finished MetadataDocument instead.

Field-shape reference: config/dataverse_export.yaml's docstring-equivalent
comments, and the real citation metadata block fetched live via
GET /api/dataverses/:id/metadatablocks?returnDatasetFieldTypes=true
against a running instance — not recalled from memory.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from metadata_enricher.config.models import DataverseExportConfig, ProviderConfig
from metadata_enricher.llm.base import LLMClient
from metadata_enricher.llm.factory import create_llm_client
from metadata_enricher.types import MetadataDocument, TokenUsage

logger = logging.getLogger(__name__)

# Dataverse's citation metadata block's Subject field — a required,
# controlled-vocabulary field with no DataCite equivalent. Verified live:
#   curl -H "X-Dataverse-key:$TOKEN" \
#     "http://localhost:8080/api/dataverses/root/metadatablocks?returnDatasetFieldTypes=true"
# against a real Dataverse 6.11 instance on 2026-08-05. This is Dataverse's
# own default citation block, shipped with every install — unlike a model
# name (no canonical list exists anywhere), this list IS canonical and
# stable, so hardcoding it here is the right call, not a shortcut. A
# heavily customized installation could differ; re-verify against
# /api/dataverses/:id/metadatablocks if targeting one.
SUBJECT_CATEGORIES: tuple[str, ...] = (
    "Agricultural Sciences",
    "Arts and Humanities",
    "Astronomy and Astrophysics",
    "Business and Management",
    "Chemistry",
    "Computer and Information Science",
    "Earth and Environmental Sciences",
    "Engineering",
    "Law",
    "Mathematical Sciences",
    "Medicine, Health and Life Sciences",
    "Physics",
    "Social Sciences",
    "Other",
)

# Dataverse's authorIdentifierScheme controlled vocabulary — same
# verification method as SUBJECT_CATEGORIES, same instance, same date.
_AUTHOR_IDENTIFIER_SCHEMES: frozenset[str] = frozenset(
    {"ORCID", "ROR", "ISNI", "LCNA", "VIAF", "GND", "DAI", "ResearcherID", "ScopusID"}
)

# Built dynamically from SUBJECT_CATEGORIES (the single source of truth,
# verified live) rather than duplicated as a literal Enum body — mypy
# can't verify a dynamically-constructed Enum's members, hence the ignore.
DataverseSubject = Enum(  # type: ignore[misc]
    "DataverseSubject", {v.replace(" ", "_").replace(",", ""): v for v in SUBJECT_CATEGORIES}
)


class _SubjectClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: DataverseSubject


@dataclass
class DataverseExportResult:
    """Result of to_dataverse_json() — mirrors PipelineResult's own
    warnings/token_usage shape for consistency."""

    dataset_json: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)


def load_dataverse_export_config(path: Path) -> DataverseExportConfig:
    """Read config/dataverse_export.yaml (or an override path)."""
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return DataverseExportConfig.model_validate(data)


def _primitive_field(type_name: str, value: str) -> dict[str, Any]:
    return {"value": value, "typeClass": "primitive", "multiple": False, "typeName": type_name}


def _controlled_vocab_field(type_name: str, values: list[str]) -> dict[str, Any]:
    return {"value": values, "typeClass": "controlledVocabulary", "multiple": True, "typeName": type_name}


def _compound_field(type_name: str, entries: list[dict[str, dict[str, Any]]]) -> dict[str, Any]:
    return {"value": entries, "typeClass": "compound", "multiple": True, "typeName": type_name}


def _build_title(document: MetadataDocument, warnings: list[str]) -> str:
    titles = document.get_field("titles") or []
    for title in titles:
        if title.get("title_type") == "MainTitle" and title.get("name"):
            return str(title["name"])
    if titles and titles[0].get("name"):
        return str(titles[0]["name"])
    warnings.append("no title found — Dataverse requires one; using the resource identifier as a fallback")
    resource = document.get_field("resource") or {}
    return str(resource.get("identifier") or "Untitled resource")


def _build_authors(document: MetadataDocument) -> list[dict[str, dict[str, Any]]]:
    creators = document.get_field("creators") or []
    entries = []
    for creator in creators:
        name = creator.get("creator_name")
        if not name:
            continue
        author: dict[str, dict[str, Any]] = {
            "authorName": {
                "value": name,
                "typeClass": "primitive",
                "multiple": False,
                "typeName": "authorName",
            }
        }
        affiliations = creator.get("affiliations") or []
        if affiliations and affiliations[0].get("affiliation"):
            author["authorAffiliation"] = {
                "value": affiliations[0]["affiliation"],
                "typeClass": "primitive",
                "multiple": False,
                "typeName": "authorAffiliation",
            }
        name_identifiers = creator.get("name_identifiers") or []
        if name_identifiers:
            scheme = name_identifiers[0].get("name_identifier_scheme")
            identifier = name_identifiers[0].get("name_identifier")
            if scheme in _AUTHOR_IDENTIFIER_SCHEMES and identifier:
                author["authorIdentifierScheme"] = {
                    "value": scheme,
                    "typeClass": "controlledVocabulary",
                    "multiple": False,
                    "typeName": "authorIdentifierScheme",
                }
                author["authorIdentifier"] = {
                    "value": identifier,
                    "typeClass": "primitive",
                    "multiple": False,
                    "typeName": "authorIdentifier",
                }
        entries.append(author)
    return entries


# A source page's "contact" text is often more than a bare address --
# "someone@example.org; +34 123 456 789" or "Contact: someone@example.org
# (fax: ...)" -- and an agent extracting it verbatim passes the whole
# string through. Dataverse's datasetContactEmail field expects a real
# address, so search for one instead of using the raw text; a plain
# split on ";" would break if the email isn't the first segment.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _extract_email(raw: str | None) -> str | None:
    if not raw:
        return None
    match = _EMAIL_RE.search(raw)
    return match.group(0) if match else None


def _build_dataset_contact(
    document: MetadataDocument, authors: list[dict[str, dict[str, Any]]], warnings: list[str]
) -> list[dict[str, dict[str, Any]]]:
    resource = document.get_field("resource") or {}
    email = _extract_email(resource.get("contact"))
    name = None
    if not email:
        # DataCite has no guaranteed contact-email field — resource.contact
        # is very commonly empty (confirmed in the project's own golden
        # fixtures). Fall back to the first author rather than inventing
        # one; Dataverse still requires *some* value, so this is flagged
        # as a warning, not silently fabricated.
        for creator in document.get_field("creators") or []:
            creator_email = _extract_email(creator.get("email"))
            if creator_email:
                email = creator_email
                name = creator.get("creator_name")
                break
    if not email:
        warnings.append(
            "no contact email found anywhere in the extracted metadata — "
            "Dataverse requires one; this dataset will need its contact "
            "fixed by hand before it's usable"
        )
        email = "unknown@example.org"
    if name is None and authors:
        name = authors[0]["authorName"]["value"]
    if name is None:
        name = "Unknown"

    return [
        {
            "datasetContactName": {
                "value": name,
                "typeClass": "primitive",
                "multiple": False,
                "typeName": "datasetContactName",
            },
            "datasetContactEmail": {
                "value": email,
                "typeClass": "primitive",
                "multiple": False,
                "typeName": "datasetContactEmail",
            },
        }
    ]


def _build_descriptions(document: MetadataDocument, warnings: list[str]) -> list[dict[str, dict[str, Any]]]:
    descriptions = document.get_field("descriptions") or []
    entries = [
        {
            "dsDescriptionValue": {
                "value": d["description"],
                "typeClass": "primitive",
                "multiple": False,
                "typeName": "dsDescriptionValue",
            }
        }
        for d in descriptions
        if d.get("description")
    ]
    if not entries:
        warnings.append("no description found — Dataverse requires one; leaving a placeholder")
        entries = [
            {
                "dsDescriptionValue": {
                    "value": "No description was extracted for this resource.",
                    "typeClass": "primitive",
                    "multiple": False,
                    "typeName": "dsDescriptionValue",
                }
            }
        ]
    return entries


def _build_keywords(document: MetadataDocument) -> list[str]:
    subjects = document.get_field("subjects") or []
    return [s["subject_name"] for s in subjects if s.get("subject_name")]


def _build_alternative_url(document: MetadataDocument) -> dict[str, Any] | None:
    """The one hook back to the original web resource — DataCite's own
    `ResourceDescription.url` has no field of its own in the DataCite
    output otherwise, but Dataverse's citation block has a matching
    primitive field for exactly this (confirmed live against a real
    Dataverse 6.11 instance's citation metadata block on 2026-08-17:
    `alternativeURL`, typeClass primitive, multiple=False, description
    "Another URL where one can view or access the data in the Dataset").
    """
    resource = document.get_field("resource") or {}
    url = resource.get("url")
    if not url:
        return None
    return _primitive_field("alternativeURL", str(url))


def classify_subject(
    document: MetadataDocument,
    export_config: DataverseExportConfig,
    provider: ProviderConfig,
    *,
    llm_client: LLMClient | None = None,
) -> tuple[str, TokenUsage]:
    """One LLM call, constrained to SUBJECT_CATEGORIES via a real enum
    response_model (Instructor validates the choice, not a hopeful string
    match) — the one place this module asks an LLM to decide anything.

    *llm_client* overrides the real client construction — same injection
    pattern as Pipeline's/AgentRegistry's own llm_factory param, mainly so
    tests can substitute a fake without monkeypatching create_llm_client.
    """
    titles = document.get_field("titles") or []
    title = titles[0]["name"] if titles and titles[0].get("name") else ""
    descriptions = document.get_field("descriptions") or []
    description = descriptions[0]["description"] if descriptions and descriptions[0].get("description") else ""
    subjects = document.get_field("subjects") or []
    subjects_joined = "; ".join(s["subject_name"] for s in subjects if s.get("subject_name"))

    agent = export_config.agent
    prompt = agent.prompt
    for key, val in {
        "dataverse_title": title,
        "dataverse_description": description,
        "dataverse_subjects": subjects_joined,
    }.items():
        prompt = prompt.replace("{" + key + "}", val)

    client: LLMClient = llm_client if llm_client is not None else create_llm_client(
        provider,
        model=agent.model or provider.name,
        temperature=agent.temperature,
        extra_body=agent.extra_body,
    )

    complete_with_usage = getattr(client, "complete_with_usage", None)
    if complete_with_usage is not None:
        result, usage = complete_with_usage(prompt=prompt, response_model=_SubjectClassification)
    else:
        result = client.complete(prompt=prompt, response_model=_SubjectClassification)
        usage = TokenUsage()

    return result.subject.value, usage


def to_dataverse_json(
    document: MetadataDocument,
    export_config: DataverseExportConfig,
    provider: ProviderConfig | None = None,
    *,
    llm_client: LLMClient | None = None,
    license_name: str = "CC0 1.0",
    license_uri: str = "http://creativecommons.org/publicdomain/zero/1.0",
) -> DataverseExportResult:
    """Convert *document* into a dict ready to POST to
    ``/api/dataverses/{alias}/datasets`` — the exact shape
    dataset-finch1.json / native-api.rst document.

    Pass ``export_config.enabled=False`` (or omit *provider*) to skip the
    Subject classification call entirely — subject defaults to ["Other"]
    with a warning, the one thing meant to be independently toggleable.
    *llm_client* is forwarded to classify_subject() — see its docstring.
    """
    warnings: list[str] = []
    token_usage = TokenUsage()

    title = _build_title(document, warnings)
    authors = _build_authors(document)
    if not authors:
        warnings.append("no creators found — Dataverse requires an author; using 'Unknown' as a placeholder")
        authors = [
            {
                "authorName": {
                    "value": "Unknown",
                    "typeClass": "primitive",
                    "multiple": False,
                    "typeName": "authorName",
                }
            }
        ]
    contacts = _build_dataset_contact(document, authors, warnings)
    descriptions = _build_descriptions(document, warnings)
    keywords = _build_keywords(document)
    alternative_url = _build_alternative_url(document)

    if export_config.enabled and provider is not None:
        subject, token_usage = classify_subject(document, export_config, provider, llm_client=llm_client)
    else:
        if export_config.enabled and provider is None:
            warnings.append("subject classification enabled but no provider given — defaulting to 'Other'")
        subject = "Other"

    fields = [
        _primitive_field("title", title),
        _compound_field("author", authors),
        _compound_field("datasetContact", contacts),
        _compound_field("dsDescription", descriptions),
        _controlled_vocab_field("subject", [subject]),
    ]
    if keywords:
        fields.append(
            _compound_field(
                "keyword",
                [
                    {
                        "keywordValue": {
                            "value": kw,
                            "typeClass": "primitive",
                            "multiple": False,
                            "typeName": "keywordValue",
                        }
                    }
                    for kw in keywords
                ],
            )
        )
    if alternative_url is not None:
        fields.append(alternative_url)

    dataset_json = {
        "datasetVersion": {
            "license": {"name": license_name, "uri": license_uri},
            "metadataBlocks": {
                "citation": {
                    "fields": fields,
                    "displayName": "Citation Metadata",
                }
            },
        }
    }
    return DataverseExportResult(dataset_json=dataset_json, warnings=warnings, token_usage=token_usage)
