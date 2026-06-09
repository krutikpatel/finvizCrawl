# How To Run Guide

## 1) What This Project Does
This project scrapes Finviz data for a single ticker, fetches linked news articles, and writes structured JSON outputs for LLM analysis.

Primary command:
- `finzwiz scrape --ticker <TICKER>`

## 2) Prerequisites
- OS: macOS or Linux
- Python: `3.11+` recommended by project metadata (current local runs were validated on Python `3.9.6`, but align to `3.11+` when possible)
- Internet access for live scraping

## 3) Quick Start (Current System)
From project root:
- `/Users/krutik/Documents/GptCodexWorkspace/finzwizCrawl1`

Create venv and install deps:
```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Run tests:
```bash
.venv/bin/python -m pytest -q
```

Run a scrape:
```bash
PYTHONPATH=src .venv/bin/python -m finzwiz.cli scrape --ticker AAPL
```

## 4) Using Makefile / Script
Make targets:
```bash
make install
make test
make bootstrap
```

One-command script:
```bash
./scripts/run_tests.sh
```

## 5) Output Locations
For ticker `AAPL`, files are written to:
- `data/AAPL/<YYYY-MM-DD>/finviz_quote.json`
- `data/AAPL/<YYYY-MM-DD>/finviz_news.json`
- `data/AAPL/<YYYY-MM-DD>/articles/<ARTICLE_ID>.json`
- `data/AAPL/<YYYY-MM-DD>/run_manifest.json`
- `data/AAPL/seen_urls.jsonl`

## 6) Important Runtime Notes
- Date partitioning and timestamps follow US Pacific semantics.
- Dedup window is 15 days (`config.yaml`).
- Successful recent URLs are skipped; recent failed URLs are retried.
- Some article URLs may still fail due to paywalls/403/blocked sources; failures are recorded in `run_manifest.json`.

## 7) Setup On a Different System
### Option A: Copy project directory directly
1. Copy the full project folder to the new machine.
2. Open terminal in copied folder.
3. Recreate virtual environment:
```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```
4. Validate setup:
```bash
.venv/bin/python -m pytest -q
```
5. Run scraper:
```bash
PYTHONPATH=src .venv/bin/python -m finzwiz.cli scrape --ticker META
```

### Option B: Fresh clone + install
1. Clone/copy source files to target machine.
2. Ensure `config.yaml` exists in repo root.
3. Run install/test commands from Option A.

## 8) Recommended Production-Like Setup (Different System)
- Use Python `3.11+`.
- Create a dedicated OS user for running scraper jobs.
- Schedule CLI externally (cron/systemd) since in-app scheduler is out of scope.
- Keep `data/` on persistent storage and back it up.
- Rotate/archive old output folders as needed.

## 9) Common Troubleshooting
- `ModuleNotFoundError`:
  - Ensure venv is used (`.venv/bin/python ...`) and deps installed from `requirements.txt`.
- DNS/connection issues:
  - Verify outbound network and DNS resolution to `finviz.com`.
- SSL/OpenSSL warning:
  - If seen on older macOS Python builds, prefer a newer Python distribution (3.11+).
- Non-zero exit code:
  - Check `run_manifest.json` and stderr for quote-page fatal errors.

