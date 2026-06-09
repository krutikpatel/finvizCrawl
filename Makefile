VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest

.PHONY: venv install test bootstrap run-workflow workflow-install workflow-uninstall workflow-status workflow-logs

venv:
	python3 -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

test:
	$(PYTEST) -q

bootstrap: install test

# Run the full workflow (scrape + analysis) right now
run-workflow:
	bash scripts/workflow.sh

# Manage the twice-daily launchd job (8 AM + 4 PM)
workflow-install:
	bash scripts/manage_workflow.sh install

workflow-uninstall:
	bash scripts/manage_workflow.sh uninstall

workflow-status:
	bash scripts/manage_workflow.sh status

workflow-logs:
	bash scripts/manage_workflow.sh logs

