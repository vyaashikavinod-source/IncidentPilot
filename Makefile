PYTHON ?= python

.PHONY: install check test lint typecheck format
install:
	$(PYTHON) -m pip install -e ".[api,data,worker,observability,dev]"
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

