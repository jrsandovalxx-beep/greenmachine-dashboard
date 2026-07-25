# GreenMachine developer commands.
# `make check` runs exactly the gates CI runs, in the same order, so a green
# local check means a green pipeline.

.PHONY: help install format lint typecheck test check clean

help:
	@echo "install    Install the package in editable mode with dev dependencies"
	@echo "format     Format the codebase with ruff"
	@echo "lint       Lint the codebase with ruff"
	@echo "typecheck  Run mypy in strict mode over src/"
	@echo "test       Run the pytest suite"
	@echo "check      Run every CI gate: format check, lint, typecheck, test"
	@echo "clean      Remove build artefacts and tool caches"

install:
	python -m pip install --upgrade pip
	pip install -e ".[dev]"
	pre-commit install

format:
	ruff check . --fix
	ruff format .

lint:
	ruff check .

typecheck:
	mypy --strict src/

test:
	pytest

check:
	ruff format --check .
	ruff check .
	mypy --strict src/
	pytest

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name "*.egg-info" -prune -exec rm -rf {} +
