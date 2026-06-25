.PHONY: install test test-regression lint typecheck run clean record-golden live-eval

install:
	uv sync --extra dev

test:
	uv run pytest --cov=metadata_enricher --cov-report=term-missing

test-regression:
	uv run pytest tests/test_regression.py -m regression -v

lint:
	uv run ruff check src/ tests/

typecheck:
	uv run mypy src/

run:
	uv run metagen

record-golden:
	uv run python scripts/record_golden.py

live-eval:
	uv run python scripts/run_live_eval.py

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
