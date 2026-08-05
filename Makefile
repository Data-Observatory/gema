.PHONY: install install-visor test test-visor test-regression lint typecheck run build-visor clean record-golden live-eval

install:
	uv sync --extra dev

install-visor:
	uv sync --extra dev --extra visor --group visor-build

test:
	uv run pytest --cov=metadata_enricher --cov-report=term-missing

test-visor:
	uv run pytest visor/tests -v

test-regression:
	uv run pytest tests/test_regression.py -m regression -v

lint:
	uv run ruff check src/ tests/

typecheck:
	uv run mypy src/

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
