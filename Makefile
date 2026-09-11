PYTHON ?= python

.PHONY: install install-locked lock check test lint typecheck format
install:
	$(PYTHON) -m pip install -e ".[api,data,worker,observability,dev]"
install-locked:
	$(PYTHON) -m pip install --require-hashes --requirement requirements-dev.lock
	$(PYTHON) -m pip install --no-deps -e .
lock:
	$(PYTHON) -m piptools compile --pre --resolver=backtracking --generate-hashes --strip-extras --extra=api --extra=data --extra=worker --extra=observability --output-file=requirements.lock pyproject.toml
	$(PYTHON) -m piptools compile --pre --resolver=backtracking --generate-hashes --strip-extras --all-extras --output-file=requirements-dev.lock pyproject.toml
check: lint typecheck test
test:
	$(PYTHON) -m pytest
lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
typecheck:
	$(PYTHON) -m mypy
format:
	$(PYTHON) -m ruff format .
