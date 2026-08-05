"""Architecture guard: visor must consume metadata_enricher directly, never
metadata_enricher.cli or the metagen CLI itself — see the visor plan doc's
hard architecture rule. Mirrors tests/test_orchestrator.py's source-scanning
pattern for the "no hardcoded agent names" invariant, but parses the AST
(rather than substring-matching) so this doesn't false-positive on the CLI
being *mentioned* in a docstring/comment — only real imports and real
subprocess shell-outs count as violations.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_VISOR_DIR = Path(__file__).resolve().parent.parent


def _visor_source_files() -> list[Path]:
    return [
        p
        for p in _VISOR_DIR.rglob("*.py")
        if "tests" not in p.relative_to(_VISOR_DIR).parts
    ]


def _imports_cli_module(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "metadata_enricher.cli" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "metadata_enricher.cli":
                return True
            if node.module == "metadata_enricher" and any(
                alias.name == "cli" for alias in node.names
            ):
                return True
    return False


_SUBPROCESS_CALL_NAMES = {
    ("subprocess", "run"),
    ("subprocess", "call"),
    ("subprocess", "Popen"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("os", "system"),
    ("os", "popen"),
}


def _call_target(node: ast.Call) -> tuple[str, str] | None:
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return (func.value.id, func.attr)
    return None


def _contains_metagen_string(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "metagen" in sub.value:
            return True
    return False


def _shells_out_to_metagen(tree: ast.Module) -> bool:
    """Catch subprocess.run(["metagen", ...]) / os.system("metagen ...") style
    evasions of the "import the library directly" rule. Deliberately scoped
    to actual subprocess/os.system call sites — a bare string constant
    mentioning "metagen" (e.g. the ~/.config/metagen/ path convention
    find_config() itself already uses) is not a violation on its own."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_target(node) in _SUBPROCESS_CALL_NAMES:
            if _contains_metagen_string(node):
                return True
    return False


class TestNoCliImport:
    @pytest.mark.parametrize(
        "path", _visor_source_files(), ids=lambda p: str(p.relative_to(_VISOR_DIR))
    )
    def test_no_cli_module_import(self, path: Path) -> None:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not _imports_cli_module(tree), (
            f"{path.relative_to(_VISOR_DIR)} imports metadata_enricher.cli — visor must import "
            "directly from metadata_enricher (the library), never from its CLI layer. "
            "See the visor architecture rule."
        )

    @pytest.mark.parametrize(
        "path", _visor_source_files(), ids=lambda p: str(p.relative_to(_VISOR_DIR))
    )
    def test_no_metagen_subprocess_shellout(self, path: Path) -> None:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not _shells_out_to_metagen(tree), (
            f"{path.relative_to(_VISOR_DIR)} shells out to the 'metagen' CLI via subprocess/os.system "
            "— visor must call metadata_enricher's library API directly instead."
        )

    def test_visor_source_files_is_non_empty(self) -> None:
        """Guard the guard: if this ever returns [], the parametrized tests
        above silently collect zero cases and stop protecting anything."""
        assert len(_visor_source_files()) > 0


class TestDetectorItself:
    """The detector must actually fire on real violations — otherwise the
    class above passing proves nothing."""

    @pytest.mark.parametrize(
        "snippet",
        [
            "import metadata_enricher.cli",
            "from metadata_enricher.cli import app",
            "from metadata_enricher import cli",
        ],
    )
    def test_flags_real_cli_imports(self, snippet: str) -> None:
        assert _imports_cli_module(ast.parse(snippet))

    def test_does_not_flag_library_imports(self) -> None:
        assert not _imports_cli_module(
            ast.parse("from metadata_enricher.pipeline import Pipeline")
        )

    def test_does_not_flag_prose_mention_in_docstring(self) -> None:
        """The whole reason this uses ast, not substring-matching — a
        docstring explaining the rule must not trip the rule itself."""
        assert not _imports_cli_module(
            ast.parse('"""Never import metadata_enricher.cli here."""\nimport os')
        )

    def test_flags_metagen_subprocess_call(self) -> None:
        assert _shells_out_to_metagen(ast.parse('subprocess.run(["metagen", "process"])'))

    def test_does_not_flag_unrelated_string(self) -> None:
        assert not _shells_out_to_metagen(ast.parse('x = "not the cli command"'))
