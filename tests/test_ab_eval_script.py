"""Smoke test for scripts/ab_eval_cdif_vs_datacite.py — the A/B diagnostic
comparing CDIF-generated-then-DataCite-exported output against the frozen
pre-pivot DataCite-direct-generation baseline.

LLM calls are cache-replayed (same guarantee as test_regression.py) — no
API key needed. Identifier enrichment/DOI resolution still make small,
real GET requests to public registries (ROR/ORCID/ISNI/doi.org), same
pre-existing behavior as test_regression.py itself — see the script's own
module docstring. Not a regression gate: the two sides are expected to
have genuinely diverged since the baseline was frozen (Open Questions
#16-#23 all changed CDIF-side shapes after that snapshot was taken), so
this only asserts the comparison itself runs cleanly and produces a real
number per resource — not that every resource clears the similarity
threshold.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import ab_eval_cdif_vs_datacite as ab_eval_module  # noqa: E402
from ab_eval_cdif_vs_datacite import (  # noqa: E402
    BASELINE_EXPECTED,
    CDIF_CACHE,
    CDIF_INPUTS,
    _load_baseline,
    _run_cdif_as_datacite,
    main,
)

pytestmark = [pytest.mark.regression]

_STEMS = sorted(p.stem for p in BASELINE_EXPECTED.glob("*.json")) if BASELINE_EXPECTED.exists() else []
_HAS_BASELINE = len(_STEMS) > 0 and CDIF_INPUTS.exists()


@pytest.fixture(autouse=True)
def _readonly_cdif_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect CDIF_CACHE to a scratch copy for the duration of each test.

    diskcache opens cache.db read-write even for a pure hit, rewriting
    internal SQLite bookkeeping -- so every run of this test file left the
    committed fixture showing as modified in `git status` (Bin X -> X
    bytes, zero real content change), found in review 2026-09-07.
    _run_cdif_as_datacite/main() read the module-level CDIF_CACHE global
    at call time, so monkeypatching the module attribute (not the
    already-imported name above) is what actually redirects them."""
    if not CDIF_CACHE.exists():
        return
    dest = tmp_path / "cache"
    shutil.copytree(CDIF_CACHE, dest)
    monkeypatch.setattr(ab_eval_module, "CDIF_CACHE", dest)


@pytest.mark.skipif(not _HAS_BASELINE, reason="Baseline fixtures not present.")
class TestAbEvalScript:
    def test_run_cdif_as_datacite_produces_valid_datacite_dict(self) -> None:
        """Cache-replay + crosswalk succeeds and yields a DataCite-shaped dict."""
        actual = _run_cdif_as_datacite(_STEMS[0])
        assert isinstance(actual, dict)
        assert "resource" in actual

    def test_load_baseline_reads_frozen_snapshot(self) -> None:
        expected = _load_baseline(_STEMS[0])
        assert isinstance(expected, dict)
        assert "resource" in expected

    def test_main_runs_cleanly_over_all_fixtures(self) -> None:
        """main() must not raise for any fixture -- pipeline cache-replay and
        the crosswalk must both succeed for every resource, regardless of
        whether the resulting similarity clears the threshold."""
        exit_code = main([])
        assert exit_code in (0, 1)
