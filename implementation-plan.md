# Implementation Plan

## 1) Architecture Strategy
- Build a layered CLI app: `cli -> orchestrator -> providers -> storage/dedup`.
- Keep implementation HTTP-only in v1, but define provider interfaces so Playwright can be added later without major refactor.
- Enforce fail-fast behavior: if Finviz quote page fetch/parse fails, stop run and skip article scraping.
- Generate deterministic JSON via explicit schema builders with fixed keys, null defaults, and stable key ordering.

## 2) Scraping Strategy
- Use a shared `requests.Session` with custom `User-Agent`, timeout, and retry settings from config.
- Parse Finviz HTML with `BeautifulSoup` using `lxml` parser.
- Extract quote snapshot and Finviz news rows from the single quote page only (no tab scraping in v1).
- Normalize news items into schema fields (`headline`, `publisher`, `published_at_raw`, `url`, `article_id`).
- For each eligible article URL, fetch via HTTP and extract main text with fallback pipeline:
  1. `trafilatura` as primary extractor.
  2. `readability-lxml` + `BeautifulSoup` cleanup as fallback.
- Apply dedup rules using exact URL strings from Finviz:
  - recent success (within 15 days) -> skip
  - recent failure -> retry
  - older/unseen -> fetch

## 3) Planned Python Packages
- `requests`: HTTP client and session management.
- `beautifulsoup4`: HTML parsing for Finviz/news extraction.
- `lxml`: parser backend for performance and stability.
- `trafilatura`: primary article content extraction.
- `readability-lxml`: fallback article extraction.
- `PyYAML`: config loading from `config.yaml`.
- `python-dateutil`: parsing varied date/time strings from source pages.
- `pytest`: unit testing framework.
- `freezegun` (or `pytest-freezegun`): deterministic tests for time-based dedup logic.

## 4) Runtime and Data Handling Choices
- Date partitioning and timestamps follow US Pacific timezone semantics (`America/Los_Angeles`).
- Article fetches run in parallel; target default concurrency is `5` and remains configurable.
- Quote-page failure is fatal (non-zero exit); article-level failures are non-fatal but recorded in manifest and article JSON.
- Output remains file-based only, including `seen_urls.jsonl` for dedup state.

## 5) Test Plan (Unit Only)
- Verify deterministic `article_id` generation from URL.
- Verify dedup behavior across 15-day window and status-based retry rules.
- Verify config defaults and overrides.
- Verify JSON serialization uses fixed schema fields and null placeholders.
