# PANW AI FP&A Copilot — common tasks.  Run `make help` to see all targets.
# The venv is created/used automatically; no need to `source` it yourself.

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.DEFAULT_GOAL := help
.PHONY: help setup run pipeline ingest forecast backtest variance signals summary verify chat test clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

$(VENV):  ## Create the virtualenv + install deps (runs automatically when missing)
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r requirements.txt

setup: $(VENV)  ## Install/refresh dependencies

run: $(VENV)  ## Launch the Streamlit dashboard (auto-loads .env)
	$(VENV)/bin/streamlit run app/dashboard.py

pipeline: ingest signals summary  ## Rebuild all data artifacts (data + signals + brief)

ingest: $(VENV)  ## Stage 0: build + reconcile financials.csv
	$(PY) -m src.ingest

forecast: $(VENV)  ## Stage 1: probabilistic forecast
	$(PY) -m src.forecast

backtest: $(VENV)  ## Stage 2: walk-forward validation report
	$(PY) -m src.backtest

variance: $(VENV)  ## Stage 3: variance bridge + attribution
	$(PY) -m src.variance

signals: $(VENV)  ## Stage 4: transcript signals -> signals.csv
	$(PY) -m src.signals

summary: $(VENV)  ## Stage 5: verified CFO executive brief
	$(PY) -m src.summary

verify: $(VENV)  ## Number-verification harness demo (clean vs corrupted)
	$(PY) -m src.verify

chat: $(VENV)  ## Ask the chat agent (use Q="your question")
	$(PY) -m src.chat "$(Q)"

test: $(VENV)  ## Run the pytest suite
	$(PY) -m pytest tests/ -q

clean:  ## Remove caches and generated artifacts (keeps raw SEC data)
	rm -rf src/__pycache__ tests/__pycache__ .pytest_cache
	rm -f data/signals.csv data/exec_brief.md data/backtest_report.json data/variance_report.json
