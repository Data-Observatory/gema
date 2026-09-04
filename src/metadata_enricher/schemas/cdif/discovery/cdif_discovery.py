"""CDIF Discovery profile Schema implementation (JSON-LD).

Implements the ``Schema`` Protocol (``schemas/base.py``) exactly like
``DataCiteSchema46`` does, retargeted to CDIF's Discovery profile
(vendored at ``schemas/cdif/discovery/`` -- see ``VENDORED_SHA.txt``).
This is the sole LLM generation target as of the CDIF/Croissant pivot
(docs/codata_mcp_croissant_cdifspecs.md sec 3.5); DataCiteSchema46 is
exporter-only going forward.

Field naming: internal field names (config/agents.yaml's ``fields:``
entries, ``AgentResult.field_name``, this model's Python attributes) are
snake_case, never the raw CURIE string -- ``agents/base.py`` does
``getattr(result, field_name)``, which requires a valid Python
identifier, so a literal ``"schema:name"`` cannot be a field name.  Each
attribute instead carries its real CURIE as a Pydantic ``alias``
(e.g. ``schema_name`` <-> ``"schema:name"``).  ``merge_agent_results``
translates every field to its CURIE key when writing into
``MetadataDocument.fields``, so the final document is genuinely
JSON-LD-shaped (CURIE keys throughout) rather than a mix of the two.

Normalizer design differs deliberately from DataCiteSchema46's: that
class's per-field bespoke normalizers exist to coerce a decade of loosely
-shaped legacy agent output (multiple historical key aliases, string
fallbacks) into DataCite's fixed shape.  CDIF generation starts fresh --
agent prompts are written against these exact field shapes from day one,
so a handful of generic, shape-based normalizers (string / dict-list /
string-list / single-dict) cover every field; no per-field alias-key
handling is needed.  This can grow bespoke per-field normalizers later if
real LLM output turns out messier than assumed, the same way DataCite's
did over time.

SHACL conformance (``check_shacl_conformance``) and JSON-LD framing
(``frame_output``) -- wiring decision (docs/cdif_pivot_implementation_plan.md
"Step 6"): ``check_shacl_conformance`` **is** wired into ``pipeline.py`` as
a new, non-blocking post-merge step mirroring the existing PID-validation
step, gated behind ``PipelineConfig.validate_shacl_conformance`` (default
``False`` -- see that field's own docstring for why: every real recorded
golden fixture fails this check today, mostly for reasons outside gema's
control -- see below -- so defaulting it on would flood every existing
user with warnings before there's a way to act on most of them).
``frame_output`` stays an available-but-uncalled utility method, the same
status ``validate_output`` itself already has: nothing in gema consumes
CDIF's canonical framed shape yet (no output writer, no exporter reads
it), so wiring it into the pipeline would produce a value nobody uses.
Both methods are exercised directly against real golden fixtures in
``tests/test_shacl_and_framing.py``, which also records what was found:
every fixture produces *real*, sensible violations (not JSON-LD-conversion
noise -- that class of false positive was the Step 5.5 bug, already
fixed) -- most commonly (a) ``dcterms:conformsTo`` only ever names
``https://w3id.org/cdif/discovery/1.0``, never the ``.../cdif/core/1.0``
URI the shapes also require (CDIFDiscoveryProfile emits only the one URI
today, see ``_inject_envelope`` below), (b) nested ``schema:identifier``/
``schema:license`` entries carry no ``@type``, so SHACL's ``sh:class``
checks can't recognize them as ``schema:PropertyValue``/typed nodes, and
(c) at least one fixture (``sample_input06.json``) is missing real content
for both required OR-groups (no ``schema:license``/``conditionsOfAccess``,
no ``schema:url``/``distribution``) -- a genuine gap in that recording,
not a framework bug. None of this is "fixed" here -- see the module-level
docstring note in ``docs/cdif_pivot_implementation_plan.md``'s Step 6
writeup; fixing the fixtures/generation to force conformance was
explicitly out of scope for this pass.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from importlib import resources
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from metadata_enricher.types import AgentResult, MetadataDocument, jsonld_list_unwrap

logger = logging.getLogger(__name__)

_PACKAGE = "metadata_enricher.schemas.cdif.discovery"

# Required @context prefixes (vendored schema.json's @context.required) plus
# dqv, which this profile's dqv:hasQualityMeasurement field needs. Richer
# forms some fields could use (spdx:checksum, geosparql geometry, time
# intervals) would need their own prefixes too -- not added since this
# profile's normalizers keep those fields as flat dicts in v1, not the
# fully nested shapes that would require them (see module docstring).
_BASE_CONTEXT: dict[str, str] = {
    "schema": "http://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "prov": "http://www.w3.org/ns/prov#",
    "dqv": "http://www.w3.org/ns/dqv#",
}

# Known-dead as of the vendored SHA's date (2026-09-04) -- CDIF has no
# tagged releases, so its own spec-mandated conformance URIs 404 today.
# See docs/codata_mcp_croissant_cdifspecs.md sec 8: emit anyway, this is a
# defect in CDIF's own infrastructure, not gema's, and is expected to
# resolve once CDIF tags a real release.
_CONFORMS_TO = "https://w3id.org/cdif/discovery/1.0"


def _read_vendored_sha() -> str:
    content = (resources.files(_PACKAGE) / "VENDORED_SHA.txt").read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.startswith("commit_sha="):
            return line.split("=", 1)[1].strip()
    raise ValueError("VENDORED_SHA.txt missing a commit_sha= line")


class CDIFDiscoveryOutputModel(BaseModel):
    """Validated output model for the CDIF Discovery profile.

    All fields optional except where the required-floor validator below
    enforces presence -- agents populate this progressively, same as
    DataCiteOutputModel. Field order matches this profile's Q2 mapping
    in docs/cdif_pivot_implementation_plan.md, grouped by required floor,
    conditional OR-groups, then the rest.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    reasoning: str = Field(default="")

    # -- Envelope fields (never agent-generated; injected by
    # merge_agent_results -- see that method) -- declared here only so
    # validate_output() can check the required floor on a fully-merged
    # document. Never listed in any agent's config/agents.yaml `fields:`.
    id_: str = Field(default="", alias="@id")
    type_: list[str] = Field(default_factory=list, alias="@type")
    context_: dict[str, str] = Field(default_factory=dict, alias="@context")
    schema_date_modified: str = Field(default="", alias="schema:dateModified")
    schema_subject_of: dict[str, Any] = Field(default_factory=dict, alias="schema:subjectOf")

    # -- Required floor (agent-generated part) --
    schema_name: str = Field(default="", alias="schema:name")
    schema_identifier: list[dict[str, Any]] = Field(
        default_factory=list, alias="schema:identifier"
    )

    # -- Conditional OR-groups: license|conditionsOfAccess, url|distribution --
    schema_license: list[dict[str, Any]] = Field(default_factory=list, alias="schema:license")
    schema_conditions_of_access: list[dict[str, Any]] = Field(
        default_factory=list, alias="schema:conditionsOfAccess"
    )
    schema_url: str = Field(default="", alias="schema:url")
    schema_distribution: list[dict[str, Any]] = Field(
        default_factory=list, alias="schema:distribution"
    )

    # -- Other properties (Q2 mapping) --
    schema_description: str = Field(default="", alias="schema:description")
    schema_additional_type: str = Field(default="", alias="schema:additionalType")
    schema_same_as: list[dict[str, Any]] = Field(default_factory=list, alias="schema:sameAs")
    schema_version: str = Field(default="", alias="schema:version")
    schema_in_language: str = Field(default="", alias="schema:inLanguage")
    schema_date_created: str = Field(default="", alias="schema:dateCreated")
    schema_date_published: str = Field(default="", alias="schema:datePublished")
    schema_copyright_year: str = Field(default="", alias="schema:copyrightYear")
    schema_related_link: list[dict[str, Any]] = Field(
        default_factory=list, alias="schema:relatedLink"
    )
    schema_publishing_principles: str = Field(default="", alias="schema:publishingPrinciples")
    schema_keywords: list[dict[str, Any]] = Field(default_factory=list, alias="schema:keywords")
    schema_about: list[dict[str, Any]] = Field(default_factory=list, alias="schema:about")
    schema_audience: list[dict[str, Any]] = Field(default_factory=list, alias="schema:audience")
    # schema:creator arrives from merge_agent_results wrapped as a JSON-LD
    # {"@list": [...]} construct (constraint C4) -- the validator below
    # unwraps it back to a plain list for this model's internal shape, the
    # same way types.jsonld_list_unwrap does for every other consumer.
    # validate_output() checks *content*, not exact JSON-LD wire shape, so
    # this field never needs to round-trip the wrapper itself.
    schema_creator: list[dict[str, Any]] = Field(default_factory=list, alias="schema:creator")
    schema_contributor: list[dict[str, Any]] = Field(
        default_factory=list, alias="schema:contributor"
    )
    schema_publisher: dict[str, Any] = Field(default_factory=dict, alias="schema:publisher")
    schema_provider: list[dict[str, Any]] = Field(default_factory=list, alias="schema:provider")
    schema_copyright_holder: str = Field(default="", alias="schema:copyrightHolder")
    schema_funding: list[dict[str, Any]] = Field(default_factory=list, alias="schema:funding")
    schema_citation: list[dict[str, Any]] = Field(default_factory=list, alias="schema:citation")
    schema_spatial_coverage: list[dict[str, Any]] = Field(
        default_factory=list, alias="schema:spatialCoverage"
    )
    schema_temporal_coverage: list[str] = Field(
        default_factory=list, alias="schema:temporalCoverage"
    )
    schema_measurement_technique: list[str] = Field(
        default_factory=list, alias="schema:measurementTechnique"
    )
    schema_variable_measured: list[dict[str, Any]] = Field(
        default_factory=list, alias="schema:variableMeasured"
    )
    dqv_quality_measurement: list[dict[str, Any]] = Field(
        default_factory=list, alias="dqv:hasQualityMeasurement"
    )
    prov_generated_by: dict[str, Any] = Field(default_factory=dict, alias="prov:wasGeneratedBy")
    prov_derived_from: list[dict[str, Any]] = Field(
        default_factory=list, alias="prov:wasDerivedFrom"
    )

    @field_validator("schema_creator", mode="before")
    @classmethod
    def _unwrap_creator_for_validation(cls, value: Any) -> Any:
        return jsonld_list_unwrap(value)

    @model_validator(mode="after")
    def _check_required_floor(self) -> CDIFDiscoveryOutputModel:
        """Enforces the vendored schema's allOf[0].required floor plus its
        two anyOf conditional groups (see docs/cdif_pivot_implementation_plan.md
        Q1 research findings). Only meaningful on a fully-merged document --
        per-agent partial output never satisfies this and must not be
        validated against it (see build_output_model, which never carries
        this validator over to its per-agent subset models)."""
        missing = [
            alias
            for attr, alias in (
                ("id_", "@id"),
                ("type_", "@type"),
                ("context_", "@context"),
                ("schema_name", "schema:name"),
                ("schema_identifier", "schema:identifier"),
                ("schema_date_modified", "schema:dateModified"),
                ("schema_subject_of", "schema:subjectOf"),
            )
            if not getattr(self, attr)
        ]
        if missing:
            raise ValueError(f"CDIF Discovery required floor missing: {', '.join(missing)}")
        if not (self.schema_license or self.schema_conditions_of_access):
            raise ValueError(
                "CDIF Discovery requires schema:license or schema:conditionsOfAccess"
            )
        if not (self.schema_url or self.schema_distribution):
            raise ValueError("CDIF Discovery requires schema:url or schema:distribution")
        return self


# Attribute name -> CURIE alias, derived once from the model so
# merge_agent_results can translate agent-produced field names into real
# JSON-LD keys without hand-maintaining a second copy of this mapping.
_ALIAS_BY_ATTR: dict[str, str] = {
    name: (info.alias or name) for name, info in CDIFDiscoveryOutputModel.model_fields.items()
}

# Fields never agent-generated -- excluded from build_output_model (no
# agent should ever be asked to produce these) and from merge_agent_results'
# per-result loop (they are injected separately, once, after the loop).
_ENVELOPE_ATTRS: frozenset[str] = frozenset(
    {"id_", "type_", "context_", "schema_date_modified", "schema_subject_of"}
)


class CDIFDiscoveryProfile:
    """CDIF Discovery profile implementation of the Schema Protocol.

    Vendored artifacts live in this package's directory (schema.json,
    frame.jsonld, shacl.ttl, crosswalk.xlsx, VENDORED_SHA.txt) -- see that
    file for provenance and the manual re-sync policy (spec sec 6.2).
    """

    def __init__(self) -> None:
        self._agent_model_cache: dict[tuple[str, ...], type[BaseModel]] = {}
        self._version = _read_vendored_sha()

    # ------------------------------------------------------------------
    # Schema identity (Protocol properties)
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "cdif-discovery"

    @property
    def version(self) -> str:
        # A commit SHA, not a semver -- CDIF has no tagged releases (spec
        # sec 6.3). Read from VENDORED_SHA.txt, not hardcoded here, so the
        # two never drift.
        return self._version

    @property
    def output_model(self) -> type[BaseModel]:
        return CDIFDiscoveryOutputModel

    def build_output_model(self, fields: list[str]) -> type[BaseModel]:
        """Per-agent response model -- same cache/digest-naming contract as
        DataCiteSchema46.build_output_model (see that docstring; the
        cache-key-stability requirement is identical here). Deliberately
        never includes the required-floor validator: a single agent's
        output is always a partial subset of the full document and would
        always fail that check."""
        key = tuple(fields)
        cached = self._agent_model_cache.get(key)
        if cached is not None:
            return cached

        field_definitions: dict[str, Any] = {}
        for name in ("reasoning", *fields):
            if name in _ENVELOPE_ATTRS:
                continue
            info = CDIFDiscoveryOutputModel.model_fields.get(name)
            if info is None:
                continue
            field_definitions[name] = (info.annotation, deepcopy(info))

        digest_source = "|".join(
            f"{name}:{annotation!r}" for name, (annotation, _) in field_definitions.items()
        )
        digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
        model = create_model(
            f"CDIFDiscoveryOutputModel_{digest}",
            __base__=BaseModel,
            __config__=ConfigDict(extra="allow", populate_by_name=True),
            **field_definitions,
        )
        self._agent_model_cache[key] = model
        return model

    # ------------------------------------------------------------------
    # Field ordering
    # ------------------------------------------------------------------

    _FIELD_ORDER: ClassVar[list[str]] = [
        _ALIAS_BY_ATTR[attr]
        for attr in CDIFDiscoveryOutputModel.model_fields
        if attr != "reasoning"
    ]

    def get_field_order(self) -> list[str]:
        return list(self._FIELD_ORDER)

    _REQUIRED_FIELDS: ClassVar[list[str]] = [
        "schema:name",
        "schema:identifier",
        "schema:subjectOf",
    ]

    def get_required_fields(self) -> list[str]:
        """Flat subset of the real required floor -- the two anyOf
        conditional groups (license/conditionsOfAccess, url/distribution)
        can't be expressed as a flat list (this is the same contract
        DataCiteSchema46.get_required_fields uses; MetadataMerger only
        warns on missing entries here, never raises). validate_output()
        enforces the full floor including both conditional groups."""
        return list(self._REQUIRED_FIELDS)

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    def validate_output(self, raw: dict[str, Any]) -> CDIFDiscoveryOutputModel:
        """Validates a fully-merged document (CURIE-keyed, as produced by
        merge_agent_results) against the complete required floor. Not
        currently wired into pipeline.py's runtime flow -- same as
        DataCiteSchema46.validate_output today -- available for direct use
        (tests, a future CLI `validate` step, or the SHACL/framing helpers
        below)."""
        return CDIFDiscoveryOutputModel(**raw)

    # ------------------------------------------------------------------
    # SHACL conformance + JSON-LD framing (see module docstring for the
    # wiring decision -- check_shacl_conformance is called from
    # pipeline.py when opted in; frame_output stays available-but-uncalled)
    # ------------------------------------------------------------------

    def check_shacl_conformance(self, doc: MetadataDocument) -> list[str]:
        """Non-blocking SHACL conformance check against the vendored
        ``shacl.ttl`` shapes (CDIF's own ``discoveryRules.shacl`` --
        see ``VENDORED_SHA.txt``).

        Converts *doc.fields* to a real RDF graph by round-tripping it
        through JSON and rdflib's ``json-ld`` parser, which resolves
        property names strictly via the document's own ``@context`` --
        this is exactly the mechanism Step 5.5
        (docs/cdif_pivot_implementation_plan.md) had to fix a bug in
        (bare, non-CURIE nested keys silently vanishing during
        expansion instead of erroring). ``advanced=True`` is required
        because several of the vendored shapes use ``sh:SPARQLTarget``,
        an advanced-features SHACL construct pyshacl only evaluates
        with that flag set.

        Never raises: this is a diagnostic aid, not a generation gate
        (see module docstring). Any infrastructure failure -- a
        malformed document, an internal rdflib/pyshacl error -- is
        logged as a warning and degrades to an empty list, indistinguishable
        from "conformant" to a caller that only checks truthiness. Callers
        that need to tell "conformant" apart from "check didn't run" should
        watch the log instead.

        Returns one human-readable string per ``sh:ValidationResult`` in
        the returned report graph (never the raw Turtle report) -- each
        including the violation message, the SHACL shape responsible, and
        the offending focus node when pyshacl reports one.
        """
        try:
            import pyshacl
            from rdflib import RDF, Graph
            from rdflib.namespace import SH

            data_graph = Graph()
            data_graph.parse(data=json.dumps(doc.fields), format="json-ld")

            shacl_text = (resources.files(_PACKAGE) / "shacl.ttl").read_text(encoding="utf-8")
            shacl_graph = Graph()
            shacl_graph.parse(data=shacl_text, format="turtle")

            conforms, results_graph, _results_text = pyshacl.validate(
                data_graph,
                shacl_graph=shacl_graph,
                data_graph_format="json-ld",
                shacl_graph_format="turtle",
                advanced=True,
            )
            if conforms:
                return []

            violations: list[str] = []
            for result in results_graph.subjects(RDF.type, SH.ValidationResult):
                messages = [str(m) for m in results_graph.objects(result, SH.resultMessage)]
                message = "; ".join(messages) if messages else "SHACL constraint violated"
                shapes = [str(s) for s in results_graph.objects(result, SH.sourceShape)]
                focus_nodes = [str(f) for f in results_graph.objects(result, SH.focusNode)]
                parts = [message]
                if shapes:
                    parts.append(f"shape={shapes[0]}")
                if focus_nodes:
                    parts.append(f"focus_node={focus_nodes[0]}")
                violations.append(" | ".join(parts))
            return violations
        except Exception as exc:  # noqa: BLE001 - diagnostic-only, must never fail a pipeline run
            logger.warning("SHACL conformance check failed to run: %s", exc)
            return []

    def frame_output(self, doc: MetadataDocument) -> dict[str, Any]:
        """JSON-LD framing via the vendored ``frame.jsonld`` (CDIF's own
        ``CDIFDiscovery-frame.jsonld`` -- see ``VENDORED_SHA.txt``).

        Produces CDIF's own canonical, node-shaped rendering of
        *doc.fields* (typically a ``{"@context", "@graph": [...]}``
        envelope -- the vendored frame matches more than one node per
        document, e.g. the Dataset and its ``schema:subjectOf``
        CatalogRecord, so results normally carry more than one ``@graph``
        entry). Available-but-uncalled utility method -- see module
        docstring for why nothing wires this in yet.

        Never raises: on any failure (malformed input, a pyld/rdflib
        internal error) logs a warning and returns a plain deep copy of
        *doc.fields* unchanged, so callers always get some usable dict
        back, never an exception or ``None``.
        """
        try:
            from pyld import jsonld

            frame = json.loads((resources.files(_PACKAGE) / "frame.jsonld").read_text(encoding="utf-8"))
            framed: dict[str, Any] = jsonld.frame(doc.fields, frame)
            return framed
        except Exception as exc:  # noqa: BLE001 - never raise, degrade to the unchanged input
            logger.warning("JSON-LD framing failed: %s", exc)
            return deepcopy(doc.fields)

    # ------------------------------------------------------------------
    # Normalize field (dispatch)
    # ------------------------------------------------------------------

    def normalize_field(self, field_name: str, value: object) -> object:
        method_name = self._NORMALIZER_DISPATCH.get(field_name)
        if method_name is not None:
            return getattr(self, method_name)(value)
        return value

    _NORMALIZER_DISPATCH: ClassVar[dict[str, str]] = {}

    # -- Generic shape-based normalizers (see module docstring) ---------

    def _normalize_string(self, value: object) -> str:
        if isinstance(value, list):
            value = next((v for v in value if v), "") if value else ""
        if isinstance(value, dict):
            value = next(iter(value.values()), "")
        return str(value).strip() if value else ""

    def _normalize_string_list(self, value: object) -> list[str]:
        items = value if isinstance(value, list) else [value]
        return [str(item).strip() for item in items if item and str(item).strip()]

    def _normalize_dict_list(self, value: object) -> list[dict[str, Any]]:
        items = value if isinstance(value, list) else [value]
        result: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict) and item:
                result.append(item)
            elif isinstance(item, str) and item.strip():
                # A bare string where a nested JSON-LD object was expected
                # (DefinedTerm/Person/Organization/LabeledLink/etc. all
                # define their human-readable label as schema:name) --
                # CURIE-key the fallback the same way a real nested entry
                # would be keyed, not a bare "name".
                result.append({"schema:name": item.strip()})
        return result

    def _normalize_single_dict(self, value: object) -> dict[str, Any]:
        if isinstance(value, list):
            value = value[0] if value else {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            return {"schema:name": value.strip()}
        return {}

    # ------------------------------------------------------------------
    # Merge agent results
    # ------------------------------------------------------------------

    def merge_agent_results(self, results: list[AgentResult]) -> MetadataDocument:
        doc = MetadataDocument()

        for result in results:
            if result.error or result.value is None:
                continue
            if result.field_name in _ENVELOPE_ATTRS:
                # Defensive: no agent config should ever declare one of
                # these, but never let a misconfigured agent overwrite an
                # envelope field.
                continue

            curie_key = _ALIAS_BY_ATTR.get(result.field_name, result.field_name)
            normalized = self.normalize_field(result.field_name, result.value)
            existing = doc.get_field(curie_key)

            if existing is None:
                doc.set_field(curie_key, normalized)
            elif isinstance(existing, list) and isinstance(normalized, list):
                doc.set_field(curie_key, existing + normalized)
            elif isinstance(existing, dict) and isinstance(normalized, dict):
                merged = dict(existing)
                for k, v in normalized.items():
                    if k not in merged or (v and not merged.get(k)):
                        merged[k] = v
                doc.set_field(curie_key, merged)
            else:
                doc.set_field(curie_key, normalized)

        # schema:creator is JSON-LD order-preserving per the vendored
        # schema's own field description ("Use the JSON-LD @list construct
        # to preserve author order") -- an {"@list": [...]} object, not a
        # bare array, unlike schema:contributor (constraint C4 in
        # docs/cdif_pivot_implementation_plan.md). Agents still emit a
        # plain list (the natural Instructor/structured-output shape);
        # wrapping is a pure JSON-LD serialization concern applied once
        # here, after generation, so it never leaks into agent prompts.
        creator_list = doc.get_field("schema:creator")
        if isinstance(creator_list, list):
            doc.set_field("schema:creator", {"@list": creator_list})

        # C6: schema:sameAs has minItems: 1 in the vendored schema -- an
        # empty list is invalid, so omit the key entirely rather than
        # emit []. Only schema:sameAs and @type carry a minItems
        # constraint in the vendored schema; @type is always non-empty
        # (injected by _inject_envelope below).
        if doc.get_field("schema:sameAs") == []:
            del doc.fields["schema:sameAs"]

        self._inject_envelope(doc)

        # Order fields per _FIELD_ORDER, leftover/unknown fields appended
        # in original order (mirrors DataCiteSchema46.merge_agent_results).
        ordered: dict[str, Any] = {}
        for field_name in self._FIELD_ORDER:
            if field_name in doc.fields:
                ordered[field_name] = doc.fields[field_name]
        for field_name in doc.fields:
            if field_name not in ordered:
                ordered[field_name] = doc.fields[field_name]
        doc.fields = ordered

        return doc

    def _inject_envelope(self, doc: MetadataDocument) -> None:
        """Injects the fields no agent ever generates: @id, @type,
        @context, schema:dateModified (a processing-time fact), and
        schema:subjectOf (the CatalogRecord describing this metadata
        record itself, per the vendored schema's real example). See
        docs/codata_mcp_croissant_cdifspecs.md sec 5/sec 8."""
        doc.set_field("@context", dict(_BASE_CONTEXT))
        doc.set_field("@type", ["schema:Dataset"])
        doc.set_field("@id", self._derive_id(doc))
        doc.set_field("schema:dateModified", datetime.now(UTC).date().isoformat())

        record_id = f"{doc.get_field('@id')}#metadata"
        # dcterms:conformsTo points at CDIF's own spec-mandated conformance
        # URI. It 404s as of this vendored SHA's date (2026-09-04) -- CDIF
        # has no tagged releases yet, so this is a known, temporary defect
        # in CDIF's own infrastructure, not gema's. Emitted anyway per
        # docs/codata_mcp_croissant_cdifspecs.md sec 8's explicit decision:
        # omitting it would make gema's output non-conformant by CDIF's own
        # stated rule today, and the URI is expected to resolve once CDIF
        # tags a real release.
        doc.set_field(
            "schema:subjectOf",
            {
                "@id": record_id,
                "@type": ["schema:Dataset"],
                "schema:additionalType": ["dcat:CatalogRecord"],
                "schema:about": {"@id": doc.get_field("@id")},
                "dcterms:conformsTo": [{"@id": _CONFORMS_TO}],
            },
        )

    def _derive_id(self, doc: MetadataDocument) -> str:
        """Prefers a resolvable URI from schema:identifier (e.g. a DOI);
        falls back to a generated urn when nothing resolvable was
        extracted. Never empty -- @id is part of the required floor."""
        for entry in doc.get_field("schema:identifier", []) or []:
            if isinstance(entry, dict):
                candidate = entry.get("schema:url") or entry.get("schema:value") or ""
                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                    return candidate
        logger.warning("No resolvable identifier found; generating a placeholder @id")
        return f"urn:gema:generated:{uuid.uuid4().hex}"


# ------------------------------------------------------------------
# Build dispatch table after class definition (mirrors DataCiteSchema46's
# pattern -- see that module).
# ------------------------------------------------------------------
CDIFDiscoveryProfile._NORMALIZER_DISPATCH = {
    "schema_name": "_normalize_string",
    "schema_description": "_normalize_string",
    "schema_additional_type": "_normalize_string",
    "schema_version": "_normalize_string",
    "schema_in_language": "_normalize_string",
    "schema_date_created": "_normalize_string",
    "schema_date_published": "_normalize_string",
    "schema_copyright_year": "_normalize_string",
    "schema_publishing_principles": "_normalize_string",
    "schema_copyright_holder": "_normalize_string",
    "schema_url": "_normalize_string",
    "schema_identifier": "_normalize_dict_list",
    "schema_same_as": "_normalize_dict_list",
    "schema_related_link": "_normalize_dict_list",
    "schema_keywords": "_normalize_dict_list",
    "schema_about": "_normalize_dict_list",
    "schema_audience": "_normalize_dict_list",
    "schema_creator": "_normalize_dict_list",
    "schema_contributor": "_normalize_dict_list",
    "schema_provider": "_normalize_dict_list",
    "schema_license": "_normalize_dict_list",
    "schema_conditions_of_access": "_normalize_dict_list",
    "schema_funding": "_normalize_dict_list",
    "schema_citation": "_normalize_dict_list",
    "schema_spatial_coverage": "_normalize_dict_list",
    "schema_variable_measured": "_normalize_dict_list",
    "dqv_quality_measurement": "_normalize_dict_list",
    "prov_derived_from": "_normalize_dict_list",
    "schema_distribution": "_normalize_dict_list",
    "schema_temporal_coverage": "_normalize_string_list",
    "schema_measurement_technique": "_normalize_string_list",
    "schema_publisher": "_normalize_single_dict",
    "prov_generated_by": "_normalize_single_dict",
}
