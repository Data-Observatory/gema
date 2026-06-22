.PHONY: install test lint typecheck run clean

install:
	uv sync --extra dev

test:
	uv run pytest --cov=metadata_enricher --cov-report=term-missing

lint:
	uv run ruff check src/ tests/

typecheck:
	uv run mypy src/

run:
	uv run metagen

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
