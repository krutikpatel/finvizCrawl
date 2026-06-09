# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
make install          # creates .venv and installs requirements.txt

# Tests
make test             # runs pytest -q
.venv/bin/python -m pytest tests/test_dedup.py -v   # single test file

# Run the scraper
PYTHONPATH=src .venv/bin/python -m finzwiz.cli scrape --ticker AAPL
PYTHONPATH=src .venv/bin/python -m finzwiz.cli scrape --ticker AAPL --force

# Automated workflow (scrape + sentiment analysis)
make run-workflow           # run right now (foreground)
make workflow-install       # register twice-daily launchd job (8 AM + 4 PM PT)
make workflow-uninstall     # remove the launchd job
make workflow-status        # check if job is registered
make workflow-logs          # tail today's log
```

The `finzwiz` entry point (from `pyproject.toml`) only works after `pip install -e .`; for development use the `PYTHONPATH=src` form above.

## Architecture

`run.py` is the orchestration core. It:
1. Loads config and sets up paths under `data/<TICKER>/<YYYY-MM-DD>/`.
2. Calls `HttpFinvizProvider.fetch_quote()` — fatal if this fails (exit 10).
3. Runs each news URL through `resolve_news_url()` then `DedupStore.decide()`.
4. Dispatches article fetches in a `ThreadPoolExecutor` (`max_concurrency` from config).
5. Updates dedup state after each fetch, then calls `dedup_store.flush()`.
6. Writes `run_manifest.json` always (even on fatal quote failure).

**Module responsibilities:**
- `providers/finviz_http.py` — HTTP fetch + BeautifulSoup/lxml parsing of the Finviz quote page. `QuoteParseError` is the fatal signal. Parses snapshot table, company, price, and news rows.
- `articles/http.py` — Article fetch using trafilatura as primary extractor, readability-lxml as fallback. `success=False` when no text extracted (non-fatal).
- `dedup.py` — `DedupStore` loads `seen_urls.jsonl` into memory, keyed by exact resolved URL. `article_id_from_url()` returns `sha256(url)[:24]`. Decisions: `new`, `forced`, `skipped_recent` (recent + `fetched_ok`), `retry_failed_recent` (recent + `fetched_failed`).
- `urls.py` — `resolve_news_url()` resolves relative Finviz URLs to absolute; returns `URLResolution` with a nullable `resolved_url`.
- `models.py` — Pure functions building fixed-schema dicts (`quote_schema`, `news_schema`, `article_schema`, `manifest_schema`). Key ordering is enforced by dict literal order, not sorting.
- `storage.py` — Atomic JSON/JSONL writes.
- `config.py` — Loads `config.yaml` into typed dataclasses.
- `providers/base.py` — `QuoteData`, `NewsItem` dataclasses and `QuoteProvider` Protocol.

**Dependency injection for tests:** `run_scrape()` accepts `quote_provider_cls` and `article_fetcher_cls` kwargs so tests can pass stub classes without patching.

## Key invariants

- All timestamps are `America/Los_Angeles` (Pacific) via `zoneinfo.ZoneInfo`.
- Dedup key is the **resolved** URL, not the raw Finviz URL.
- Article ID is `sha256(resolved_url)[:24]`.
- `seen_urls.jsonl` is the only state persisted between runs; no database.
- JSON outputs: UTF-8, 2-space pretty-print, fixed keys with `null` placeholders, `schema_version` always present.
- Exit codes: `0` success, `2` bad input/config, `10+` fatal runtime error.

## Automated workflow

`scripts/workflow.sh` is the twice-daily automation entry point. It:
1. Loops over `$FINZWIZ_TICKERS` (default `TSLA`, space-separated).
2. Runs `finzwiz scrape` for each ticker — skips analysis if scrape fails.
3. Calls `claude --print` (Claude Code CLI, non-interactive) with a structured prompt to read new articles and append to `sentiment_log.jsonl` + regenerate `sentiment_summary.json`.

The sentiment analysis step uses Claude Code's own session (no `ANTHROPIC_API_KEY` required) via the `--print` flag of the `claude` CLI at `/opt/homebrew/bin/claude`.

`scripts/com.finzwiz.workflow.plist` is a macOS `launchd` agent that fires at 8:00 AM and 4:00 PM local time. Managed via `scripts/manage_workflow.sh install|uninstall|status|logs`.

To add tickers, edit the `FINZWIZ_TICKERS` key in the plist and reload: `make workflow-install`.

Log files: `logs/workflow-YYYY-MM-DD.log` (per-run detail) and `logs/launchd.log` (launchd stdout/stderr).

## Config

`config.yaml` at repo root is the default. Key fields:
- `dedup.retention_days` — 15-day rolling dedup window.
- `scraping.max_concurrency` — thread pool size for article fetches (default 5).
- `scraping.backend` — `"http"` only in v1 (Playwright is out of scope).
- `articles.include_raw_html` — keep `false`; stores full HTML inside article JSON if enabled.
