VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest

.PHONY: venv install test bootstrap run-workflow workflow-install workflow-uninstall workflow-status workflow-logs setup-email monitor-install monitor-uninstall monitor-status monitor-logs run-monitor

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

# Manage the daily monitor launchd job (9 AM weekdays)
run-monitor:
	bash monitor/manage_monitor.sh run

monitor-install:
	bash monitor/manage_monitor.sh install

monitor-uninstall:
	bash monitor/manage_monitor.sh uninstall

monitor-status:
	bash monitor/manage_monitor.sh status

monitor-logs:
	bash monitor/manage_monitor.sh logs

# One-time setup: store Gmail app password in macOS Keychain
# Usage: make setup-email EMAIL=you@gmail.com
setup-email:
	@[ -n "$(EMAIL)" ] || (echo "Usage: make setup-email EMAIL=you@gmail.com" && exit 1)
	@read -s -p "Gmail app password for $(EMAIL): " pw && echo && \
	    security add-generic-password -a "$(EMAIL)" -s "finzwiz-smtp" -w "$$pw" && \
	    echo "Password stored in Keychain for $(EMAIL)"

