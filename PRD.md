# FinvizCrawl PRD (Implementation Locked)

## 1) Summary
Build a Python CLI that takes one stock ticker, scrapes the Finviz quote page, scrapes linked news article URLs from that page, and writes structured JSON files for LLM analysis.

Primary user: one local user (macOS/Linux).

## 2) Locked Scope (v1)
### In scope
- Single ticker input per run.
- CLI-only execution.
- Finviz quote page scraping (single page only).
- News URL extraction from that quote page.
- Article fetch + readable text extraction for each news URL.
- File-based deduplication window of 15 days per ticker.
- HTTP-based scraper implementation only.
- Stable JSON schemas with fixed fields and deterministic key ordering.

### Out of scope (v1)
- Multi-ticker input.
- Scheduling/cron inside the app.
- Finviz linked tab scraping.
- Playwright implementation.
- Any database.

## 3) User Stories
- As a user, I run one command daily for a ticker and get structured JSON outputs.
- As a user, article URLs already seen in the last 15 days are not duplicated, except retry behavior for past failures.
- As a user, if Finviz quote parsing fails, the run stops and article scraping does not proceed.

## 4) CLI Contract
### Command
- `finzwiz scrape --ticker <TICKER> [--config config.yaml] [--force]`

### Flags
- `--ticker`: required, normalized to uppercase.
- `--config`: optional path; defaults to `config.yaml`.
- `--force`: when set, re-fetch articles even if they are successful and recent.

### Date handling
- Use system date only.
- Date folder path uses local time in US Pacific timezone.
- No `--date` support in v1.

### Exit codes
- `0`: run completed (article-level failures allowed if recorded).
- `2`: invalid input/config.
- `>=10`: fatal runtime failure.
- Fatal condition: quote page fetch/parse failure must exit non-zero and skip article scraping.

## 5) Configuration Rules
`config.yaml` is source of runtime settings.

Required behavior:
- `dedup.retention_days = 15`
- dedup state file is JSONL (no DB).
- `scraping.max_concurrency` is configurable and should support `5` for article fetches.
- backend for v1 is HTTP only.

## 6) Output Layout
Root output dir from config (default `data/`):

- `data/<TICKER>/<YYYY-MM-DD>/run_manifest.json`
- `data/<TICKER>/<YYYY-MM-DD>/finviz_quote.json`
- `data/<TICKER>/<YYYY-MM-DD>/finviz_news.json`
- `data/<TICKER>/<YYYY-MM-DD>/articles/<ARTICLE_ID>.json`
- `data/<TICKER>/seen_urls.jsonl`

Where:
- `<YYYY-MM-DD>` is derived from US Pacific local system date.
- `<ARTICLE_ID>` is a stable hash from exact URL string (recommended `sha256(url)` truncated).

## 7) JSON Schema Rules
Applies to every JSON output:
- UTF-8.
- Pretty-printed (2 spaces).
- Stable key ordering.
- Fixed schema fields always present; use `null` when value is unavailable.
- Include `schema_version`.

## 8) Output Schemas
### 8.1 run_manifest.json
Required fields:
- `schema_version`
- `ticker`
- `run_date`
- `started_at`
- `finished_at`
- `timezone` (must be `America/Los_Angeles`)
- `config`
- `artifacts` (paths for quote, news, articles dir, dedup file)
- `stats`:
  - `news_links_total`
  - `news_links_new`
  - `news_links_skipped_recent`
  - `news_links_retry_failed`
  - `articles_fetched_ok`
  - `articles_failed`
- `errors` (list of structured errors)

### 8.2 finviz_quote.json
Required fields:
- `schema_version`
- `ticker`
- `source` (`name`, `url`, `fetched_at`)
- `company` (`name`, `sector`, `industry`, `country`)
- `price` (`value`, `change`, `change_percent`)
- `snapshot_table` (label-value mapping from Finviz quote page)
- `raw` (nullable, minimal fragments only)

### 8.3 finviz_news.json
Required fields:
- `schema_version`
- `ticker`
- `source` (`name`, `url`, `fetched_at`)
- `items` list with each item containing:
  - `published_at`
  - `published_at_raw`
  - `publisher`
  - `headline`
  - `url`
  - `article_id`
  - `dedup_status` (`new`, `skipped_recent`, `retry_failed_recent`, `forced`)
  - `dedup_reason`

### 8.4 articles/<ARTICLE_ID>.json
Required fields:
- `schema_version`
- `ticker`
- `source` (`name`, `url`, `fetched_at`)
- `extraction` (`method`, `success`, `error`)
- `metadata` (`title`, `byline`, `published_at`, `site_name`, `language`)
- `content` (`text`, `text_blocks`, `html`)
- `links`

For v1:
- `extraction.method` is `http`.

## 9) Deduplication and Retry Rules (15 days)
State file:
- `data/<TICKER>/seen_urls.jsonl`
- One JSON object per line.

Per-record fields:
- `url` (exact URL from Finviz; no canonicalization)
- `article_id`
- `first_seen_at`
- `last_seen_at`
- `last_fetched_at`
- `status` (`fetched_ok`, `fetched_failed`, `skipped_recent`)
- `http_status`
- `note`

Behavior:
- Dedup key is exact URL string from Finviz.
- If URL is seen within 15 days with last status `fetched_ok`, skip unless `--force`.
- If URL is seen within 15 days with last status `fetched_failed`, retry fetch.
- If URL not seen within 15 days, fetch.
- Always update dedup state after processing.

## 10) Failure Policy
- Quote page fetch/parse failure is fatal:
  - record error in manifest,
  - return non-zero exit,
  - skip article scraping entirely.
- Article failures are non-fatal:
  - continue other articles,
  - record per-article error and manifest stats.

## 11) Concurrency and Runtime Behavior
- Article fetches may run in parallel.
- Default/conventional concurrency target: `5` (configurable).
- Keep retries configurable via `config.yaml`.

## 12) Implementation Notes (v1)
- Use HTTP stack (`requests`, `beautifulsoup4`, `lxml`) for v1.
- Use readability-style extraction for article body (`readability-lxml` or equivalent).
- Keep architecture extension-friendly for optional Playwright in future, but do not implement Playwright now.

## 13) Suggested Project Structure
- `pyproject.toml`
- `src/finzwiz/__init__.py`
- `src/finzwiz/cli.py`
- `src/finzwiz/config.py`
- `src/finzwiz/models.py`
- `src/finzwiz/storage.py`
- `src/finzwiz/dedup.py`
- `src/finzwiz/providers/base.py`
- `src/finzwiz/providers/finviz_http.py`
- `src/finzwiz/articles/http.py`
- `tests/`

## 14) Acceptance Criteria
- `finzwiz scrape --ticker AAPL` creates:
  - `finviz_quote.json`
  - `finviz_news.json`
  - `articles/*.json` for eligible URLs
  - `run_manifest.json`
  - `seen_urls.jsonl`
- No tab scraping artifacts are created in v1.
- Re-run behavior:
  - successful recent URLs are skipped,
  - failed recent URLs are retried,
  - `--force` re-fetches all recent URLs.
- All datetime fields use US Pacific timezone semantics for date partitioning.
- JSON outputs use fixed schema with stable key ordering and null placeholders.

## 15) Test Requirements (pytest, unit only)
- `article_id` deterministic from URL.
- dedup decisions across statuses and 15-day window:
  - recent success -> skip
  - recent failure -> retry
  - older than 15 days -> fetch
- config parsing defaults and overrides.
- schema serialization guarantees fixed keys and null placeholders.

