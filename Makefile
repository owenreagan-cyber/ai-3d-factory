.PHONY: test check lint status verify

VENV := .venv/bin

test:
	$(VENV)/python -m pytest

check: lint

lint:
	$(VENV)/python -m compileall -q src tests

status:
	$(VENV)/factory status

verify: lint test
	$(VENV)/factory status
	$(VENV)/factory inspect-slicer
