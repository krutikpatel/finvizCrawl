# User Story 1: Daily Single-Ticker Scrape

## Story
As a user, I run one CLI command for a ticker and get structured JSON outputs from Finviz quote page data plus related news article content.

## Goal
Produce deterministic, LLM-ready files under `data/<TICKER>/<YYYY-MM-DD>/` for one ticker per run.

## CLI Contract
- Command: `finzwiz scrape --ticker <TICKER> [--config config.yaml] [--force]`
- `--ticker` is required and normalized to uppercase.
- `--config` is optional and defaults to `config.yaml`.
- `--force` bypasses dedup skip behavior for recent successful URLs.

## Inputs
- `ticker` string (example: `AAPL`).
- Runtime config from `config.yaml`.
- System date/time (US Pacific semantics for partition date).

## Processing Steps
1. Validate CLI inputs and config.
2. Build run context (`ticker`, run date, timezone, output paths).
3. Fetch Finviz quote page for ticker via HTTP.
4. Parse quote snapshot fields and news list.
5. Write `finviz_quote.json` and `finviz_news.json`.
6. For each news URL, apply dedup decision from `seen_urls.jsonl`.
7. Fetch and extract article content for eligible URLs.
8. Write one `articles/<ARTICLE_ID>.json` per processed URL.
9. Update `seen_urls.jsonl`.
10. Write `run_manifest.json` with artifacts, stats, and errors.

## Required Outputs
- `data/<TICKER>/<YYYY-MM-DD>/finviz_quote.json`
- `data/<TICKER>/<YYYY-MM-DD>/finviz_news.json`
- `data/<TICKER>/<YYYY-MM-DD>/articles/<ARTICLE_ID>.json`
- `data/<TICKER>/<YYYY-MM-DD>/run_manifest.json`
- `data/<TICKER>/seen_urls.jsonl`

## Schema Rules
- UTF-8 JSON, pretty printed (2 spaces).
- Stable key ordering.
- Fixed schema fields always present; use `null` when unknown.
- Include `schema_version` in every JSON file.

## Dedup Rules (15 Days)
- Key: exact URL string from Finviz (no canonicalization).
- Recent `fetched_ok`: skip unless `--force`.
- Recent `fetched_failed`: retry.
- Not seen within 15 days: fetch.

## Failure Policy
- Quote page fetch/parse failure is fatal:
  - exit non-zero,
  - record error in manifest,
  - do not proceed to article scraping.
- Article-level failure is non-fatal:
  - continue processing remaining URLs,
  - write failure details in article JSON + manifest stats.

## Concurrency
- Article requests can run in parallel.
- Use configurable `scraping.max_concurrency` (target default: `5`).

## Acceptance Criteria
- Running `finzwiz scrape --ticker AAPL` creates all required files for that date.
- `finviz_quote.json` contains parsed quote snapshot table.
- `finviz_news.json` contains URL list with `article_id` and dedup status.
- Re-run within 15 days:
  - successful recent URLs are skipped,
  - failed recent URLs are retried.
- `--force` re-fetches recent successful URLs.
- Quote parse failure prevents article scraping.

## Out of Scope for This Story
- Multi-ticker runs.
- Scheduler/cron.
- Finviz tab scraping.
- Playwright backend.
