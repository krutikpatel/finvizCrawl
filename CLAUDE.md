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

# Rebuild sentiment_summary.json from the log (no Claude call — pure aggregation)
PYTHONPATH=src .venv/bin/python -m finzwiz.cli rebuild-summary --ticker AAPL

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

> Full detail in `WORKFLOW.md` — phases, data flow, scoring, context management, failure modes.

`scripts/workflow.sh` is the twice-daily automation entry point. It runs four phases:

1. **Scrape** — `finzwiz scrape` for each ticker; skips analysis if scrape fails.
2. **Pre-filter (Python)** — for each ticker, reads `sentiment_log.jsonl` to find already-analyzed `article_id`s, then writes `data/<TICKER>/<DATE>/analysis_input.json` containing only new articles with text truncated to 2000 chars. Outputs the count of new articles.
3. **Single Claude call** — one `claude --print` session covering all tickers that have new articles. Claude reads each ticker's `analysis_input.json` and appends scored records to `sentiment_log.jsonl`. Claude does **not** write `sentiment_summary.json`.
4. **Rebuild summaries (Python)** — `finzwiz rebuild-summary --ticker <TICKER>` for each analyzed ticker. Pure aggregation over `sentiment_log.jsonl`; no Claude call.

The sentiment analysis step uses Claude Code's own session (no `ANTHROPIC_API_KEY` required) via the `--print` flag of the `claude` CLI at `/opt/homebrew/bin/claude`.

## Sentiment analysis design

**Why Claude only sees new articles:**
Each article is scored in isolation — Claude reads the article text and decides bullish/bearish/neutral based on what the article says. Prior articles don't change how a new article reads; if an older event is still relevant, today's articles will reference it. Sending all historical articles to Claude wastes context window: with 100 articles per ticker × 9 tickers × ~25 KB each, a naive prompt balloons to ~23 MB, hitting Claude Code's session limit after 1–2 tickers.

**Why Python rebuilds the summary, not Claude:**
`sentiment_summary.json` is pure aggregation — counts, averages, grouping by date, sorting by score. It draws on *all* historical records in `sentiment_log.jsonl`, not just today's. Python (`finzwiz rebuild-summary`) reads the full log and recomputes the summary after each run. This means the summary always reflects the complete history, and Claude's job is reduced to scoring new text only.

**The split:**
- Claude's responsibility: read `analysis_input.json` (new articles, pre-filtered, text-truncated) → append scored records to `sentiment_log.jsonl`.
- Python's responsibility: dedup check, pre-filtering, `analysis_input.json` generation, and `sentiment_summary.json` aggregation.

`scripts/com.finzwiz.workflow.plist` is a macOS `launchd` agent that fires at 8:00 AM and 4:00 PM local time. Managed via `scripts/manage_workflow.sh install|uninstall|status|logs`.

To add tickers, edit the `FINZWIZ_TICKERS` key in the plist and reload: `make workflow-install`.

Log files: `logs/workflow-YYYY-MM-DD.log` (per-run detail) and `logs/launchd.log` (launchd stdout/stderr).

## Config

`config.yaml` at repo root is the default. Key fields:
- `dedup.retention_days` — 15-day rolling dedup window.
- `scraping.max_concurrency` — thread pool size for article fetches (default 5).
- `scraping.backend` — `"http"` only in v1 (Playwright is out of scope).
- `articles.include_raw_html` — keep `false`; stores full HTML inside article JSON if enabled.
