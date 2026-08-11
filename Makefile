.PHONY: install install-visor test test-visor test-visor-live test-regression lint typecheck run build-visor clean record-golden live-eval

install:
	uv sync --extra dev

install-visor:
	uv sync --extra dev --extra visor --group visor-build

test:
	uv run pytest --cov=metadata_enricher --cov-report=term-missing

test-visor:
	uv run pytest visor/tests -p nicegui.testing.user_plugin -o asyncio_mode=auto -m "not live" -v

# Real LLM call, real wall-clock time (a full 5-agent pipeline run) — never
# run automatically, only via this explicit target. See
# visor/tests/test_app_e2e.py's docstring for why this is a hard -m split,
# not just a skip-if-no-key check.
test-visor-live:
	uv run pytest visor/tests -p nicegui.testing.user_plugin -o asyncio_mode=auto -m "live" -v

test-regression:
	uv run pytest tests/test_regression.py -m regression -v

lint:
	uv run ruff check src/ tests/ scripts/

typecheck:
	uv run mypy src/ scripts/

run:
	uv run metagen

build-visor:
	uv run pyinstaller visor/visor.spec --noconfirm

record-golden:
	uv run python scripts/record_golden.py

live-eval:
	uv run python scripts/run_live_eval.py

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
