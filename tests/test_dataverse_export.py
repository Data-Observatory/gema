"""Tests for exporters/dataverse.py — DataCite MetadataDocument -> Dataverse
native JSON, plus the one optional LLM-assisted Subject classification step.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from metadata_enricher.config.models import AgentConfig, DataverseExportConfig, ProviderConfig
from metadata_enricher.exporters.dataverse import (
    SUBJECT_CATEGORIES,
    classify_subject,
    load_dataverse_export_config,
    to_dataverse_json,
)
from metadata_enricher.types import MetadataDocument, TokenUsage

GOLDEN_FIXTURE = Path(__file__).parent / "fixtures" / "golden" / "expected" / "sample_input01.json"


class FakeLLMClient:
    """Own mock per project convention (no shared MockLLMClient) —
    complete_with_usage matching the optional duck-typed extension."""

    def __init__(self, subject_value: str = "Social Sciences", usage: TokenUsage | None = None) -> None:
        self._subject_value = subject_value
        self._usage = usage or TokenUsage(prompt_tokens=12, completion_tokens=3)
        self.last_prompt: str | None = None

    @property
    def model(self) -> str:
        return "fake-model"

    def complete(self, prompt: str, response_model: type[BaseModel], system_prompt: str | None = None, **kw: object):  # noqa: ANN201
        self.last_prompt = prompt
        return response_model(subject=self._subject_value)

    def complete_with_usage(
        self, prompt: str, response_model: type[BaseModel], system_prompt: str | None = None, **kw: object
    ):  # noqa: ANN201
        self.last_prompt = prompt
        return response_model(subject=self._subject_value), self._usage

    def complete_raw(self, prompt: str, system_prompt: str | None = None, **kw: object) -> str:
        return "unused"


def make_export_config(*, enabled: bool = True) -> DataverseExportConfig:
    return DataverseExportConfig(
        enabled=enabled,
        agent=AgentConfig(
            id="dataverse_subject_classifier",
            name="Dataverse Subject Classifier",
            fields=["subject"],
            prompt="Title: {dataverse_title}\nDescription: {dataverse_description}\nSubjects: {dataverse_subjects}",
            provider="mock",
            model="fast-model",
        ),
    )


def make_provider() -> ProviderConfig:
    return ProviderConfig(name="mock", base_url="http://localhost", api_key_env="MOCK_KEY")


def make_document(**fields: object) -> MetadataDocument:
    doc = MetadataDocument()
    for key, value in fields.items():
        doc.set_field(key, value)
    return doc


class TestTitle:
    def test_prefers_main_title(self):
        doc = make_document(
            titles=[{"name": "A Title", "title_type": "MainTitle"}],
            creators=[{"creator_name": "Someone"}],
            descriptions=[{"description": "D."}],
            resource={"contact": "someone@example.org"},
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        title_field = next(f for f in fields if f["typeName"] == "title")
        assert title_field["value"] == "A Title"
        assert result.warnings == []

    def test_falls_back_to_resource_identifier_when_no_titles(self):
        doc = make_document(titles=[], resource={"identifier": "https://example.org/x"})
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        title_field = next(f for f in fields if f["typeName"] == "title")
        assert title_field["value"] == "https://example.org/x"
        assert any("no title found" in w for w in result.warnings)


class TestAuthors:
    def test_maps_name_affiliation_and_known_identifier_scheme(self):
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            creators=[
                {
                    "creator_name": "Ministerio de Hacienda",
                    "affiliations": [{"affiliation": "Gobierno de Chile"}],
                    "name_identifiers": [{"name_identifier": "123", "name_identifier_scheme": "ISNI"}],
                }
            ],
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        author_field = next(f for f in fields if f["typeName"] == "author")
        entry = author_field["value"][0]
        assert entry["authorName"]["value"] == "Ministerio de Hacienda"
        assert entry["authorAffiliation"]["value"] == "Gobierno de Chile"
        assert entry["authorIdentifierScheme"]["value"] == "ISNI"
        assert entry["authorIdentifier"]["value"] == "123"

    def test_omits_identifier_for_unknown_scheme(self):
        """Only schemes confirmed in Dataverse's real controlled vocabulary
        get passed through — an unrecognized scheme would make dataset
        creation fail with an invalid-controlled-vocabulary error."""
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            creators=[
                {
                    "creator_name": "Someone",
                    "name_identifiers": [{"name_identifier": "999", "name_identifier_scheme": "Wikidata"}],
                }
            ],
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        author_field = next(f for f in fields if f["typeName"] == "author")
        entry = author_field["value"][0]
        assert "authorIdentifierScheme" not in entry
        assert "authorIdentifier" not in entry

    def test_defaults_to_unknown_with_warning_when_no_creators(self):
        doc = make_document(titles=[{"name": "T", "title_type": "MainTitle"}], creators=[])
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        author_field = next(f for f in fields if f["typeName"] == "author")
        assert author_field["value"][0]["authorName"]["value"] == "Unknown"
        assert any("no creators found" in w for w in result.warnings)


class TestDatasetContact:
    def test_prefers_resource_contact(self):
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            resource={"contact": "person@example.org"},
            creators=[{"creator_name": "Someone", "email": "other@example.org"}],
            descriptions=[{"description": "D."}],
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        contact_field = next(f for f in fields if f["typeName"] == "datasetContact")
        assert contact_field["value"][0]["datasetContactEmail"]["value"] == "person@example.org"
        assert result.warnings == []

    def test_falls_back_to_creator_email(self):
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            resource={"contact": ""},
            creators=[{"creator_name": "Someone", "email": "creator@example.org"}],
            descriptions=[{"description": "D."}],
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        contact_field = next(f for f in fields if f["typeName"] == "datasetContact")
        assert contact_field["value"][0]["datasetContactEmail"]["value"] == "creator@example.org"
        assert result.warnings == []

    def test_extracts_email_from_resource_contact_with_extra_data(self):
        """Regression: a source page's contact text is often more than a
        bare address ("person@example.org; +34 123 456 789") -- the raw
        string used to be passed straight through as datasetContactEmail,
        producing an invalid value Dataverse would reject."""
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            resource={"contact": "person@example.org; +34 123 456 789"},
            creators=[{"creator_name": "Someone"}],
            descriptions=[{"description": "D."}],
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        contact_field = next(f for f in fields if f["typeName"] == "datasetContact")
        assert contact_field["value"][0]["datasetContactEmail"]["value"] == "person@example.org"
        assert result.warnings == []

    def test_extracts_email_from_resource_contact_when_phone_comes_first(self):
        """A plain split on ";" would grab the phone number here instead --
        must search for the email pattern, not assume position."""
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            resource={"contact": "+34 123 456 789; person@example.org"},
            creators=[{"creator_name": "Someone"}],
            descriptions=[{"description": "D."}],
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        contact_field = next(f for f in fields if f["typeName"] == "datasetContact")
        assert contact_field["value"][0]["datasetContactEmail"]["value"] == "person@example.org"

    def test_extracts_email_from_creator_email_with_extra_data(self):
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            resource={"contact": ""},
            creators=[{"creator_name": "Someone", "email": "creator@example.org; fax: 555-1234"}],
            descriptions=[{"description": "D."}],
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        contact_field = next(f for f in fields if f["typeName"] == "datasetContact")
        assert contact_field["value"][0]["datasetContactEmail"]["value"] == "creator@example.org"

    def test_placeholder_with_warning_when_nothing_found(self):
        """Real gap in DataCite -> Dataverse mapping: DataCite has no
        guaranteed contact-email field. Must warn, never fabricate
        silently."""
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            resource={"contact": ""},
            creators=[{"creator_name": "Someone"}],
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        contact_field = next(f for f in fields if f["typeName"] == "datasetContact")
        assert contact_field["value"][0]["datasetContactEmail"]["value"] == "unknown@example.org"
        assert any("no contact email found" in w for w in result.warnings)


class TestDescriptions:
    def test_maps_all_descriptions(self):
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            descriptions=[{"description": "First."}, {"description": "Second."}],
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        desc_field = next(f for f in fields if f["typeName"] == "dsDescription")
        values = [e["dsDescriptionValue"]["value"] for e in desc_field["value"]]
        assert values == ["First.", "Second."]

    def test_placeholder_with_warning_when_empty(self):
        doc = make_document(titles=[{"name": "T", "title_type": "MainTitle"}], descriptions=[])
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        assert any("no description found" in w for w in result.warnings)


class TestKeywords:
    def test_maps_subject_names_to_keywords(self):
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            subjects=[{"subject_name": "Gastos municipales -- Chile"}, {"subject_name": "Presupuesto"}],
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        keyword_field = next(f for f in fields if f["typeName"] == "keyword")
        values = [e["keywordValue"]["value"] for e in keyword_field["value"]]
        assert values == ["Gastos municipales -- Chile", "Presupuesto"]

    def test_no_keyword_field_when_no_subjects(self):
        doc = make_document(titles=[{"name": "T", "title_type": "MainTitle"}])
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        assert not any(f["typeName"] == "keyword" for f in fields)


class TestAlternativeURL:
    def test_maps_resource_identifier_url_to_alternative_url(self):
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            resource={"identifier": "https://example.org/dataset", "identifier_type": "URL"},
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        url_field = next(f for f in fields if f["typeName"] == "alternativeURL")
        assert url_field == {
            "value": "https://example.org/dataset",
            "typeClass": "primitive",
            "multiple": False,
            "typeName": "alternativeURL",
        }

    def test_resolves_doi_identifier_through_doi_org(self):
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            resource={"identifier": "10.5880/GFZ.2.4.2021.001", "identifier_type": "DOI"},
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        url_field = next(f for f in fields if f["typeName"] == "alternativeURL")
        assert url_field["value"] == "https://doi.org/10.5880/GFZ.2.4.2021.001"

    def test_no_alternative_url_field_when_no_resource_identifier(self):
        doc = make_document(titles=[{"name": "T", "title_type": "MainTitle"}])
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        assert not any(f["typeName"] == "alternativeURL" for f in fields)


class TestSubjectClassification:
    def test_disabled_defaults_to_other_with_no_warning(self):
        """Disabling is an intentional choice, not missing data — must not warn."""
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            creators=[{"creator_name": "Someone"}],
            descriptions=[{"description": "D."}],
            resource={"contact": "someone@example.org"},
        )
        result = to_dataverse_json(doc, make_export_config(enabled=False))
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        subject_field = next(f for f in fields if f["typeName"] == "subject")
        assert subject_field["value"] == ["Other"]
        assert result.warnings == []
        assert result.token_usage == TokenUsage()

    def test_enabled_but_no_provider_warns_and_defaults_to_other(self):
        doc = make_document(titles=[{"name": "T", "title_type": "MainTitle"}])
        result = to_dataverse_json(doc, make_export_config(enabled=True), provider=None)
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        subject_field = next(f for f in fields if f["typeName"] == "subject")
        assert subject_field["value"] == ["Other"]
        assert any("no provider given" in w for w in result.warnings)

    def test_enabled_uses_injected_llm_client_result(self):
        doc = make_document(
            titles=[{"name": "T", "title_type": "MainTitle"}],
            descriptions=[{"description": "About economics and government budgets."}],
        )
        fake = FakeLLMClient(subject_value="Social Sciences")
        result = to_dataverse_json(
            doc, make_export_config(enabled=True), provider=make_provider(), llm_client=fake
        )
        fields = result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        subject_field = next(f for f in fields if f["typeName"] == "subject")
        assert subject_field["value"] == ["Social Sciences"]
        assert fake.last_prompt is not None
        assert "About economics and government budgets." in fake.last_prompt

    def test_response_constrained_to_real_categories(self):
        """Instructor validates against the enum — an LLM can't return an
        invalid category even if it tried; confirm the enum matches the
        live-verified list exactly."""
        fake = FakeLLMClient(subject_value="Chemistry")
        doc = make_document(titles=[{"name": "T", "title_type": "MainTitle"}])
        subject, usage = classify_subject(doc, make_export_config(), make_provider(), llm_client=fake)
        assert subject == "Chemistry"
        assert subject in SUBJECT_CATEGORIES
        assert usage.prompt_tokens == 12

    def test_extra_body_reaches_create_llm_client_when_no_client_injected(self, monkeypatch):
        """Regression: classify_subject built its own client via
        create_llm_client(provider, model=..., temperature=...) without
        ever forwarding agent.extra_body -- a provider/model needing a
        request-body override (e.g. disabling DeepSeek's default thinking
        mode, required alongside Instructor's forced tool_choice -- see
        config/dataverse_export.yaml's provider comment) would silently
        not get it, the same failure mode already fixed for the main
        pipeline's agents.yaml. Only exercised on the no-injected-client
        path -- llm_client= bypasses create_llm_client entirely."""
        captured: dict[str, object] = {}

        def _fake_create_llm_client(provider, **kwargs):  # noqa: ANN001, ANN201
            captured.update(kwargs)
            return FakeLLMClient()

        monkeypatch.setattr(
            "metadata_enricher.exporters.dataverse.create_llm_client", _fake_create_llm_client
        )

        config = DataverseExportConfig(
            enabled=True,
            agent=AgentConfig(
                id="dataverse_subject_classifier",
                name="Dataverse Subject Classifier",
                fields=["subject"],
                prompt="Title: {dataverse_title}",
                provider="mock",
                model="fast-model",
                extra_body={"reasoning": {"enabled": False}},
            ),
        )
        doc = make_document(titles=[{"name": "T", "title_type": "MainTitle"}])

        classify_subject(doc, config, make_provider())

        assert captured.get("extra_body") == {"reasoning": {"enabled": False}}

    def test_token_usage_flows_through_to_result(self):
        fake = FakeLLMClient(usage=TokenUsage(prompt_tokens=50, completion_tokens=10))
        doc = make_document(titles=[{"name": "T", "title_type": "MainTitle"}])
        result = to_dataverse_json(
            doc, make_export_config(enabled=True), provider=make_provider(), llm_client=fake
        )
        assert result.token_usage.prompt_tokens == 50
        assert result.token_usage.completion_tokens == 10


class TestLoadDataverseExportConfig:
    def test_loads_the_real_committed_config(self):
        path = Path(__file__).parent.parent / "config" / "dataverse_export.yaml"
        config = load_dataverse_export_config(path)
        assert config.enabled is True
        assert config.agent.id == "dataverse_subject_classifier"
        assert config.agent.provider == "openrouter"

    def test_validate_provider_exists_raises_on_unknown_provider(self):
        config = make_export_config()
        with pytest.raises(ValueError, match="not in providers"):
            config.validate_provider_exists({"some-other-provider"})

    def test_validate_provider_exists_passes_when_present(self):
        config = make_export_config()
        config.validate_provider_exists({"mock"})  # should not raise


class TestAgainstRealGoldenFixture:
    """Not a synthetic example — the actual committed golden fixture
    output from a real pipeline run, confirming the mapping holds up
    against real, messy, Spanish-language DataCite output."""

    def test_produces_a_valid_shape_from_real_output(self):
        if not GOLDEN_FIXTURE.is_file():
            pytest.skip("golden fixture not present in this checkout")
        data = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        doc = MetadataDocument()
        for key, value in data.items():
            doc.set_field(key, value)

        result = to_dataverse_json(doc, make_export_config(enabled=False))

        fields_by_name = {
            f["typeName"]: f for f in result.dataset_json["datasetVersion"]["metadataBlocks"]["citation"]["fields"]
        }
        assert fields_by_name["title"]["value"] == "Gastos municipales (presupuesto abierto)"
        assert (
            fields_by_name["author"]["value"][0]["authorName"]["value"] == "Ministerio de Hacienda"
        )
        assert fields_by_name["author"]["value"][0]["authorIdentifierScheme"]["value"] == "ISNI"
        assert fields_by_name["subject"]["value"] == ["Other"]
        assert "keyword" in fields_by_name
        # This real fixture has no resource.contact and no creator email —
        # confirms the documented gap surfaces as a warning, not a crash.
        assert any("no contact email found" in w for w in result.warnings)
