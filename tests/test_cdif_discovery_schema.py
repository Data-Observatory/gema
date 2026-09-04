"""Tests for schemas.cdif.discovery.cdif_discovery.CDIFDiscoveryProfile."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from metadata_enricher.schemas import get_registry
from metadata_enricher.schemas.base import Schema
from metadata_enricher.schemas.cdif.discovery import cdif_discovery as cdif_module
from metadata_enricher.schemas.cdif.discovery.cdif_discovery import (
    CDIFDiscoveryOutputModel,
    CDIFDiscoveryProfile,
)
from metadata_enricher.types import AgentResult, MetadataDocument


@pytest.fixture
def schema() -> CDIFDiscoveryProfile:
    return CDIFDiscoveryProfile()


class TestSchemaProperties:
    def test_name(self, schema: CDIFDiscoveryProfile) -> None:
        assert schema.name == "cdif-discovery"

    def test_version_is_the_vendored_sha(self, schema: CDIFDiscoveryProfile) -> None:
        assert schema.version == "81c28260778426cc61302105fc7191b4db360bc9"

    def test_output_model_is_a_basemodel_subclass(self, schema: CDIFDiscoveryProfile) -> None:
        assert issubclass(schema.output_model, BaseModel)

    def test_get_field_order_starts_with_envelope_fields(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        order = schema.get_field_order()
        assert order[:3] == ["@id", "@type", "@context"]

    def test_get_field_order_excludes_reasoning(self, schema: CDIFDiscoveryProfile) -> None:
        assert "reasoning" not in schema.get_field_order()

    def test_get_required_fields(self, schema: CDIFDiscoveryProfile) -> None:
        assert schema.get_required_fields() == [
            "schema:name",
            "schema:identifier",
            "schema:subjectOf",
        ]


class TestBuildOutputModel:
    def test_returns_a_basemodel_subclass(self, schema: CDIFDiscoveryProfile) -> None:
        model = schema.build_output_model(["schema_name"])
        assert issubclass(model, BaseModel)

    def test_field_order_is_reasoning_then_requested_fields(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        model = schema.build_output_model(["schema_description", "schema_name"])
        assert list(model.model_fields.keys()) == ["reasoning", "schema_description", "schema_name"]

    def test_same_fields_same_order_returns_cached_identical_type(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        a = schema.build_output_model(["schema_name", "schema_url"])
        b = schema.build_output_model(["schema_name", "schema_url"])
        assert a is b

    def test_different_order_returns_a_different_type(self, schema: CDIFDiscoveryProfile) -> None:
        a = schema.build_output_model(["schema_name", "schema_url"])
        b = schema.build_output_model(["schema_url", "schema_name"])
        assert a is not b
        assert a.__name__ != b.__name__

    def test_name_stable_across_separate_schema_instances(self) -> None:
        """type(...).__name__ is the LLM response-cache key (cache.py) --
        must be stable across process restarts / separate instances, not
        random per-instance."""
        a = CDIFDiscoveryProfile().build_output_model(["schema_name", "schema_url"])
        b = CDIFDiscoveryProfile().build_output_model(["schema_name", "schema_url"])
        assert a.__name__ == b.__name__

    def test_unknown_field_name_is_silently_skipped(self, schema: CDIFDiscoveryProfile) -> None:
        model = schema.build_output_model(["schema_name", "not_a_real_field"])
        assert "not_a_real_field" not in model.model_fields
        assert "schema_name" in model.model_fields

    def test_envelope_fields_are_never_included(self, schema: CDIFDiscoveryProfile) -> None:
        """No agent should ever be asked to produce @id/@type/@context/etc --
        those are injected by merge_agent_results, not agent-generated."""
        model = schema.build_output_model(["id_", "schema_name", "schema_subject_of"])
        assert "id_" not in model.model_fields
        assert "schema_subject_of" not in model.model_fields
        assert "schema_name" in model.model_fields

    def test_built_model_does_not_carry_the_required_floor_validator(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        """A per-agent subset model is always partial -- it must validate
        fine even without the floor fields, unlike CDIFDiscoveryOutputModel
        itself via validate_output()."""
        model = schema.build_output_model(["schema_name"])
        instance = model(schema_name="Only a name")
        assert instance.schema_name == "Only a name"  # type: ignore[attr-defined]

    def test_model_still_usable_reasoning_defaults_empty(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        model = schema.build_output_model(["schema_name"])
        instance = model(schema_name="X")
        assert instance.reasoning == ""  # type: ignore[attr-defined]

    def test_name_changes_when_a_fields_type_annotation_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fresh = CDIFDiscoveryProfile()
        before = fresh.build_output_model(["schema_url"])
        monkeypatch.setitem(
            cdif_module.CDIFDiscoveryOutputModel.model_fields,
            "schema_url",
            cdif_module.CDIFDiscoveryOutputModel.model_fields["schema_url"].__class__(
                annotation=int, default=0
            ),
        )
        fresh2 = CDIFDiscoveryProfile()
        after = fresh2.build_output_model(["schema_url"])
        assert before.__name__ != after.__name__


class TestGenericNormalizers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("  Hello  ", "Hello"),
            (["", "First", "Second"], "First"),
            ({"name": "From dict"}, "From dict"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalize_string(
        self, schema: CDIFDiscoveryProfile, value: object, expected: str
    ) -> None:
        assert schema._normalize_string(value) == expected

    def test_normalize_string_list(self, schema: CDIFDiscoveryProfile) -> None:
        assert schema._normalize_string_list(["a", "", "b", None]) == ["a", "b"]
        assert schema._normalize_string_list("solo") == ["solo"]

    def test_normalize_dict_list_wraps_bare_string(self, schema: CDIFDiscoveryProfile) -> None:
        assert schema._normalize_dict_list("Alone") == [{"name": "Alone"}]

    def test_normalize_dict_list_passes_through_dicts(self, schema: CDIFDiscoveryProfile) -> None:
        items = [{"a": 1}, {"b": 2}]
        assert schema._normalize_dict_list(items) == items

    def test_normalize_dict_list_drops_empty_dict(self, schema: CDIFDiscoveryProfile) -> None:
        assert schema._normalize_dict_list([{}, {"a": 1}]) == [{"a": 1}]

    def test_normalize_single_dict_takes_first_of_a_list(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        assert schema._normalize_single_dict([{"a": 1}, {"b": 2}]) == {"a": 1}

    def test_normalize_single_dict_wraps_bare_string(self, schema: CDIFDiscoveryProfile) -> None:
        assert schema._normalize_single_dict("Solo Publisher") == {"name": "Solo Publisher"}

    def test_normalize_single_dict_empty_list_is_empty_dict(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        assert schema._normalize_single_dict([]) == {}


class TestNormalizeFieldDispatch:
    def test_dispatches_known_field(self, schema: CDIFDiscoveryProfile) -> None:
        assert schema.normalize_field("schema_name", "  X  ") == "X"

    def test_unknown_field_passes_through_unchanged(self, schema: CDIFDiscoveryProfile) -> None:
        assert schema.normalize_field("not_a_field", [1, 2, 3]) == [1, 2, 3]

    def test_every_dispatch_entry_is_callable(self, schema: CDIFDiscoveryProfile) -> None:
        for method_name in CDIFDiscoveryProfile._NORMALIZER_DISPATCH.values():
            assert callable(getattr(schema, method_name))


class TestMergeAgentResults:
    def test_returns_a_metadata_document(self, schema: CDIFDiscoveryProfile) -> None:
        doc = schema.merge_agent_results([])
        assert isinstance(doc, MetadataDocument)

    def test_error_flagged_results_are_skipped(self, schema: CDIFDiscoveryProfile) -> None:
        results = [AgentResult(field_name="schema_name", value="X", error="boom")]
        doc = schema.merge_agent_results(results)
        assert doc.get_field("schema:name") is None

    def test_none_value_results_are_skipped(self, schema: CDIFDiscoveryProfile) -> None:
        results = [AgentResult(field_name="schema_name", value=None)]
        doc = schema.merge_agent_results(results)
        assert doc.get_field("schema:name") is None

    def test_translates_attr_name_to_curie_key(self, schema: CDIFDiscoveryProfile) -> None:
        doc = schema.merge_agent_results([AgentResult(field_name="schema_name", value="Ice")])
        assert doc.get_field("schema:name") == "Ice"
        assert "schema_name" not in doc.fields

    def test_same_field_from_multiple_results_concatenates_lists(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        results = [
            AgentResult(field_name="schema_keywords", value=[{"name": "a"}]),
            AgentResult(field_name="schema_keywords", value=[{"name": "b"}]),
        ]
        doc = schema.merge_agent_results(results)
        assert doc.get_field("schema:keywords") == [{"name": "a"}, {"name": "b"}]

    def test_field_order_matches_get_field_order(self, schema: CDIFDiscoveryProfile) -> None:
        results = [
            AgentResult(field_name="schema_url", value="https://example.org"),
            AgentResult(field_name="schema_name", value="X"),
        ]
        doc = schema.merge_agent_results(results)
        keys = list(doc.fields.keys())
        # schema:name (required-floor group) precedes schema:url (later group)
        assert keys.index("schema:name") < keys.index("schema:url")

    def test_envelope_fields_always_injected(self, schema: CDIFDiscoveryProfile) -> None:
        doc = schema.merge_agent_results([])
        for key in ("@id", "@type", "@context", "schema:dateModified", "schema:subjectOf"):
            assert key in doc.fields

    def test_a_misconfigured_agent_cannot_overwrite_envelope_fields(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        doc = schema.merge_agent_results([AgentResult(field_name="id_", value="hijacked")])
        assert doc.get_field("@id") != "hijacked"

    def test_dead_conforms_to_uri_is_emitted_anyway(self, schema: CDIFDiscoveryProfile) -> None:
        subject_of = schema.merge_agent_results([]).get_field("schema:subjectOf")
        assert subject_of["dcterms:conformsTo"] == [{"@id": "https://w3id.org/cdif/discovery/1.0"}]

    def test_id_prefers_a_resolvable_identifier(self, schema: CDIFDiscoveryProfile) -> None:
        results = [
            AgentResult(
                field_name="schema_identifier",
                value=[{"value": "https://doi.org/10.5281/zenodo.1"}],
            )
        ]
        doc = schema.merge_agent_results(results)
        assert doc.get_field("@id") == "https://doi.org/10.5281/zenodo.1"

    def test_id_falls_back_to_generated_urn_when_nothing_resolvable(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        doc = schema.merge_agent_results([])
        assert doc.get_field("@id", "").startswith("urn:gema:generated:")


class TestValidateOutput:
    def _valid_raw(self) -> dict[str, object]:
        return {
            "@id": "https://doi.org/10.1/x",
            "@type": ["schema:Dataset"],
            "@context": {"schema": "http://schema.org/"},
            "schema:dateModified": "2026-09-04",
            "schema:subjectOf": {"@id": "https://doi.org/10.1/x#metadata"},
            "schema:name": "X",
            "schema:identifier": [{"value": "https://doi.org/10.1/x"}],
            "schema:license": [{"name": "CC-BY-4.0"}],
            "schema:url": "https://example.org",
        }

    def test_valid_document_passes(self, schema: CDIFDiscoveryProfile) -> None:
        model = schema.validate_output(self._valid_raw())
        assert model.schema_name == "X"

    def test_missing_required_floor_raises(self, schema: CDIFDiscoveryProfile) -> None:
        raw = self._valid_raw()
        del raw["schema:name"]
        with pytest.raises(ValidationError, match="schema:name"):
            schema.validate_output(raw)

    def test_missing_both_license_and_conditions_of_access_raises(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        raw = self._valid_raw()
        del raw["schema:license"]
        with pytest.raises(ValidationError, match="license"):
            schema.validate_output(raw)

    def test_conditions_of_access_alone_satisfies_that_group(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        raw = self._valid_raw()
        del raw["schema:license"]
        raw["schema:conditionsOfAccess"] = [{"name": "restricted"}]
        model = schema.validate_output(raw)
        assert model.schema_conditions_of_access

    def test_missing_both_url_and_distribution_raises(self, schema: CDIFDiscoveryProfile) -> None:
        raw = self._valid_raw()
        del raw["schema:url"]
        with pytest.raises(ValidationError, match="distribution"):
            schema.validate_output(raw)

    def test_distribution_alone_satisfies_that_group(self, schema: CDIFDiscoveryProfile) -> None:
        raw = self._valid_raw()
        del raw["schema:url"]
        raw["schema:distribution"] = [{"contentUrl": "https://example.org/f.csv"}]
        model = schema.validate_output(raw)
        assert model.schema_distribution

    def test_extra_unknown_key_is_allowed(self, schema: CDIFDiscoveryProfile) -> None:
        raw = self._valid_raw()
        raw["schema:citation"] = [{"name": "Some Paper"}]
        model = schema.validate_output(raw)
        assert model.model_extra is None or "schema:citation" not in (model.model_extra or {})


class TestRegistryIntegration:
    def test_registered_under_its_name(self) -> None:
        registry = get_registry()
        assert "cdif-discovery" in registry.list_schemas()

    def test_registry_returns_a_working_schema(self) -> None:
        schema = get_registry().get("cdif-discovery")
        assert schema.name == "cdif-discovery"

    def test_satisfies_the_schema_protocol(self, schema: CDIFDiscoveryProfile) -> None:
        assert isinstance(schema, Schema)


class TestOutputModelIdentity:
    def test_output_model_is_cdif_discovery_output_model(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        assert schema.output_model is CDIFDiscoveryOutputModel

    def test_built_model_name_never_collides_with_output_model(
        self, schema: CDIFDiscoveryProfile
    ) -> None:
        built = schema.build_output_model(["schema_name"])
        assert built.__name__ != schema.output_model.__name__
