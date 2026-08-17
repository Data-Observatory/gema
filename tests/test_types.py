"""Tests for core domain types (metadata_enricher.types)."""

import pytest
from pydantic import ValidationError

from metadata_enricher.types import (
    AgentResult,
    MetadataDocument,
    ResourceDescription,
    TokenUsage,
)


class TestResourceDescription:
    """ResourceDescription: input source material."""

    def test_full_url_and_title(self):
        """Create with url and title."""
        rd = ResourceDescription(url="https://example.com", title="Test")
        assert rd.url == "https://example.com"
        assert rd.title == "Test"

    def test_url_only(self):
        """Create with url only — title is optional."""
        rd = ResourceDescription(url="https://example.com")
        assert rd.url == "https://example.com"
        assert rd.title is None

    def test_empty(self):
        """Create with no fields — all optional."""
        rd = ResourceDescription()
        assert rd.url is None
        assert rd.title is None
        assert rd.description is None
        assert rd.doi is None
        assert rd.fetched_content is None

    def test_extra_fields_allowed(self):
        """extra='allow' — arbitrary fields accepted."""
        rd = ResourceDescription(url="https://example.com", unknown_field="anything")
        assert rd.url == "https://example.com"
        assert rd.model_extra == {"unknown_field": "anything"}

    def test_partial_fields(self):
        """Only some fields provided."""
        rd = ResourceDescription(url="https://example.com", doi="10.1234/abc")
        assert rd.url == "https://example.com"
        assert rd.doi == "10.1234/abc"
        assert rd.title is None


class TestAgentResult:
    """AgentResult: single agent's extraction output."""

    def test_valid_with_list_value(self):
        """Typical case: field_name + list value."""
        result = AgentResult(field_name="titles", value=[{"title": "x"}])
        assert result.field_name == "titles"
        assert result.value == [{"title": "x"}]
        assert result.confidence is None
        assert result.error is None

    def test_empty_field_name_raises(self):
        """field_name must be non-empty (min_length=1)."""
        with pytest.raises(ValidationError):
            AgentResult(field_name="", value="x")

    def test_value_can_be_none(self):
        """None value is valid — represents a failed agent."""
        result = AgentResult(field_name="x", value=None)
        assert result.field_name == "x"
        assert result.value is None

    def test_extra_fields_forbidden(self):
        """extra='forbid' — extra fields should raise."""
        with pytest.raises(ValidationError):
            AgentResult(field_name="x", value=None, extra_field="bad")

    def test_confidence_passthrough(self):
        """confidence and error passthrough."""
        result = AgentResult(field_name="subjects", value=["science"], confidence=0.95, error=None)
        assert result.confidence == 0.95
        assert result.error is None

    def test_token_usage_default(self):
        """token_usage defaults to empty TokenUsage."""
        result = AgentResult(field_name="x", value="y")
        assert isinstance(result.token_usage, TokenUsage)
        assert result.token_usage.total_tokens == 0

    def test_string_value_valid(self):
        """value accepts str."""
        result = AgentResult(field_name="description", value="some text")
        assert result.value == "some text"

    def test_dict_value_valid(self):
        """value accepts dict."""
        result = AgentResult(field_name="resource", value={"type": "Dataset"})
        assert result.value == {"type": "Dataset"}


class TestTokenUsage:
    """TokenUsage: LLM token accounting."""

    def test_auto_calculate_total(self):
        """total_tokens auto-calculated when not provided."""
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_explicit_total_override(self):
        """Explicit total_tokens is respected."""
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=999)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 999

    def test_both_zero(self):
        """All zeros by default."""
        usage = TokenUsage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_model_defaults_to_empty_string(self):
        """No model recorded (mock client, cache hit) -> empty, not None --
        keeps callers from needing a None-check to display it."""
        usage = TokenUsage()
        assert usage.model == ""

    def test_model_explicit_value(self):
        """The provider's own resolved model id (e.g. what an OpenRouter
        '~...-latest' alias actually served) round-trips unchanged."""
        usage = TokenUsage(model="deepseek/deepseek-v4-flash-2508")
        assert usage.model == "deepseek/deepseek-v4-flash-2508"

    def test_extra_fields_forbidden(self):
        """extra='forbid'."""
        with pytest.raises(ValidationError):
            TokenUsage(prompt_tokens=1, completion_tokens=1, bad_field="nope")


class TestMetadataDocument:
    """MetadataDocument: canonical intermediate representation."""

    def test_empty_document(self):
        """Create empty document."""
        doc = MetadataDocument()
        assert doc.fields == {}

    def test_with_fields(self):
        """Accepts arbitrary fields dict."""
        doc = MetadataDocument(fields={"titles": [{"title": "Test"}]})
        assert doc.fields["titles"] == [{"title": "Test"}]

    def test_set_field(self):
        """set_field stores a value."""
        doc = MetadataDocument()
        doc.set_field("titles", [{"title": "Hello"}])
        assert doc.fields["titles"] == [{"title": "Hello"}]

    def test_get_field(self):
        """get_field retrieves a value."""
        doc = MetadataDocument(fields={"year": 2024})
        assert doc.get_field("year") == 2024

    def test_get_field_default(self):
        """get_field returns default for missing key."""
        doc = MetadataDocument()
        assert doc.get_field("nonexistent", "fallback") == "fallback"

    def test_merge(self):
        """merge updates fields from dict, skipping None."""
        doc = MetadataDocument(fields={"titles": [{"title": "A"}]})
        doc.merge({"titles": [{"title": "B"}], "descriptions": [{"text": "desc"}]})
        assert doc.fields["titles"] == [{"title": "B"}]
        assert doc.fields["descriptions"] == [{"text": "desc"}]

    def test_merge_skips_none(self):
        """merge does not overwrite with None."""
        doc = MetadataDocument(fields={"titles": [{"title": "A"}]})
        doc.merge({"titles": None, "descriptions": [{"text": "desc"}]})
        # titles should remain unchanged since merge skips None
        assert doc.fields["titles"] == [{"title": "A"}]
        assert doc.fields["descriptions"] == [{"text": "desc"}]

    def test_extra_fields_directly(self):
        """extra='allow' — arbitrary top-level fields accepted."""
        doc = MetadataDocument(fields={"a": 1}, custom="value")
        assert doc.custom == "value"  # type: ignore[attr-defined]
        assert doc.fields == {"a": 1}
