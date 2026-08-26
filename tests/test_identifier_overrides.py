"""Tests for enrichers.identifier_overrides."""

from __future__ import annotations

from pathlib import Path

from metadata_enricher.enrichers.identifier_overrides import IdentifierOverrides


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "overrides.yaml"
    path.write_text(content, encoding="utf-8")
    return path


class TestLoading:
    """IdentifierOverrides: file loading — always fails soft."""

    def test_none_path_disables_lookup(self) -> None:
        overrides = IdentifierOverrides(None)
        assert overrides.lookup("Anything") is None

    def test_missing_file_disables_lookup(self, tmp_path: Path) -> None:
        overrides = IdentifierOverrides(tmp_path / "does_not_exist.yaml")
        assert overrides.lookup("Anything") is None

    def test_empty_file_disables_lookup(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "")
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Anything") is None

    def test_malformed_yaml_disables_lookup_not_raises(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "overrides: [unterminated")
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Anything") is None

    def test_overrides_key_not_a_list_disables_lookup(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "overrides: not-a-list\n")
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Anything") is None

    def test_top_level_not_a_dict_disables_lookup(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "- just\n- a\n- list\n")
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Anything") is None

    def test_entry_missing_name_skipped(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "overrides:\n  - ror_id: https://ror.org/x\n")
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Anything") is None

    def test_entry_with_neither_id_skipped(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "overrides:\n  - name: Some Org\n")
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Some Org") is None

    def test_non_dict_entry_skipped_others_still_load(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "overrides:\n  - not-a-dict\n  - name: Some Org\n    ror_id: https://ror.org/x\n",
        )
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Some Org") is not None


class TestLookup:
    """IdentifierOverrides: lookup precedence and normalization."""

    def test_matches_by_name_case_and_punctuation_insensitive(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "overrides:\n  - name: Ministerio de Salud\n    ror_id: https://ror.org/health\n")
        overrides = IdentifierOverrides(path)
        match = overrides.lookup("  MINISTERIO, DE SALUD.  ")
        assert match is not None
        assert match.ror_id == "https://ror.org/health"
        assert match.matched_via == "override"
        assert match.status == "auto"
        assert match.confidence == 1.0

    def test_country_specific_entry_wins_over_global(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "overrides:\n"
            "  - name: Ministerio de Salud\n"
            "    ror_id: https://ror.org/global-fallback\n"
            "  - name: Ministerio de Salud\n"
            "    country: CL\n"
            "    ror_id: https://ror.org/chile-specific\n",
        )
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Ministerio de Salud", country="CL").ror_id == "https://ror.org/chile-specific"
        assert overrides.lookup("Ministerio de Salud", country="AR").ror_id == "https://ror.org/global-fallback"
        assert overrides.lookup("Ministerio de Salud").ror_id == "https://ror.org/global-fallback"

    def test_two_countries_do_not_collide(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "overrides:\n"
            "  - name: Ministerio de Salud\n"
            "    country: CL\n"
            "    ror_id: https://ror.org/cl-health\n"
            "  - name: Ministerio de Salud\n"
            "    country: AR\n"
            "    ror_id: https://ror.org/ar-health\n",
        )
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Ministerio de Salud", country="CL").ror_id == "https://ror.org/cl-health"
        assert overrides.lookup("Ministerio de Salud", country="AR").ror_id == "https://ror.org/ar-health"

    def test_country_lookup_is_case_insensitive(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "overrides:\n  - name: Some Org\n    country: CL\n    ror_id: https://ror.org/x\n")
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Some Org", country="cl") is not None

    def test_isni_only_entry(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "overrides:\n  - name: Some Org\n    isni_id: '0000000123456789'\n")
        overrides = IdentifierOverrides(path)
        match = overrides.lookup("Some Org")
        assert match is not None
        assert match.ror_id is None
        assert match.isni_id == "0000000123456789"

    def test_no_match_returns_none(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "overrides:\n  - name: Some Org\n    ror_id: https://ror.org/x\n")
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("Completely Different Org") is None

    def test_empty_name_returns_none(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "overrides:\n  - name: Some Org\n    ror_id: https://ror.org/x\n")
        overrides = IdentifierOverrides(path)
        assert overrides.lookup("") is None
