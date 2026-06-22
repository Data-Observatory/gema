"""Tests for MetadataMerger -- schema-driven merge layer."""

from __future__ import annotations

import logging


from metadata_enricher.merger import MetadataMerger
from metadata_enricher.types import AgentResult, MetadataDocument


class FakeSchema:
    def __init__(self, required=("titles",)):
        self._required = required
        self.merge_called = False

    @property
    def name(self):
        return "fake"

    @property
    def version(self):
        return "1.0"

    @property
    def output_model(self): ...

    def validate_output(self, data):
        return data

    def normalize_field(self, name, value):
        return value

    def merge_agent_results(self, results):
        self.merge_called = True
        fields = {}
        for r in results:
            fields[r.field_name] = r.value
        # Apply field ordering (mimics real schema behavior)
        ordered = {}
        for name in self.get_field_order():
            if name in fields:
                ordered[name] = fields[name]
        for name in fields:
            if name not in ordered:
                ordered[name] = fields[name]
        return MetadataDocument(fields=ordered)

    def get_field_order(self):
        return ["titles", "creators", "descriptions"]

    def get_required_fields(self):
        return list(self._required)


def _result(field_name: str, value) -> AgentResult:
    return AgentResult(field_name=field_name, value=value)


class TestMetadataMerger:
    def test_merge_empty_results(self):
        schema = FakeSchema()
        merger = MetadataMerger(schema)
        doc = merger.merge([])
        assert isinstance(doc, MetadataDocument)
        assert doc.fields == {}

    def test_merge_delegates_to_schema(self):
        schema = FakeSchema()
        merger = MetadataMerger(schema)
        merger.merge([_result("titles", "Test")])
        assert schema.merge_called is True

    def test_merge_single_result(self):
        schema = FakeSchema()
        merger = MetadataMerger(schema)
        doc = merger.merge([_result("titles", [{"name": "Test Title"}])])
        assert doc.get_field("titles") == [{"name": "Test Title"}]

    def test_merge_multiple_results(self):
        schema = FakeSchema()
        merger = MetadataMerger(schema)
        results = [
            _result("titles", [{"name": "Title A"}]),
            _result("creators", [{"creator_name": "Author A"}]),
            _result("descriptions", [{"description": "A description."}]),
        ]
        doc = merger.merge(results)
        assert doc.get_field("titles") == [{"name": "Title A"}]
        assert doc.get_field("creators") == [{"creator_name": "Author A"}]
        assert doc.get_field("descriptions") == [{"description": "A description."}]

    def test_merge_warns_on_missing_required(self, caplog):
        schema = FakeSchema(required=("titles",))
        merger = MetadataMerger(schema)
        with caplog.at_level(logging.WARNING):
            merger.merge([_result("creators", [{"creator_name": "No Title"}])])
        assert len(caplog.records) == 1
        assert "Missing required fields: titles" in caplog.text

    def test_merge_preserves_field_order(self):
        schema = FakeSchema()
        merger = MetadataMerger(schema)
        results = [
            _result("creators", [{"creator_name": "A"}]),
            _result("titles", [{"name": "T"}]),
            _result("descriptions", [{"description": "D"}]),
        ]
        doc = merger.merge(results)
        ordered = list(doc.fields.keys())
        assert ordered == ["titles", "creators", "descriptions"]

    def test_merger_under_100_lines(self):
        with open("src/metadata_enricher/merger.py") as f:
            line_count = sum(1 for _ in f)
        assert line_count < 100, f"merger.py has {line_count} lines, expected < 100"
