# User Story 2: Re-run Dedup and Retry Behavior

## Story
As a user, when I run the scraper again for the same ticker, I want previously successful recent URLs skipped and previously failed recent URLs retried, so output is fresh without duplication.

## Goal
Implement deterministic re-run behavior for article scraping using `seen_urls.jsonl` with a 15-day rolling window and exact URL matching.

## Scope
- Applies to one ticker per run.
- Uses exact Finviz URL strings as dedup keys (no URL normalization).
- Uses file-based state only (`seen_urls.jsonl`), no database.

## Inputs
- `ticker` (required CLI arg).
- `--force` flag (optional).
- `dedup.retention_days` and `dedup.seen_urls_filename` from `config.yaml`.
- Existing `data/<TICKER>/seen_urls.jsonl` state (if present).

## Processing Rules
1. Load dedup state records from `data/<TICKER>/seen_urls.jsonl`.
2. Keep latest state per exact URL using `last_seen_at`.
3. For each Finviz news URL in current run:
4. If URL seen within 15 days and status is `fetched_ok`:
5. `--force=false`: skip article fetch (`dedup_status=skipped_recent`).
6. `--force=true`: fetch article (`dedup_status=forced`).
7. If URL seen within 15 days and status is `fetched_failed`: retry fetch (`dedup_status=retry_failed_recent`).
8. If URL not seen or older than 15 days: fetch article (`dedup_status=new`).
9. Update dedup state after each decision/result with current timestamps and final status.

## Required Outputs
- Updated `data/<TICKER>/seen_urls.jsonl`.
- Updated `data/<TICKER>/<YYYY-MM-DD>/finviz_news.json` with `dedup_status` and `dedup_reason` per item.
- Article JSON files written only for URLs selected for fetch.
- Updated `run_manifest.json` stats:
  - `news_links_total`
  - `news_links_new`
  - `news_links_skipped_recent`
  - `news_links_retry_failed`
  - `articles_fetched_ok`
  - `articles_failed`

## State File Schema (`seen_urls.jsonl`)
Each JSONL record must include:
- `url`
- `article_id`
- `first_seen_at`
- `last_seen_at`
- `last_fetched_at`
- `status` (`fetched_ok`, `fetched_failed`, `skipped_recent`)
- `http_status`
- `note`

## Failure/Edge Cases
- Corrupt/missing dedup file: treat as empty state and continue.
- Duplicate URLs in same run: process once for fetch decision, but preserve per-item reporting in `finviz_news.json`.
- Failed article fetch on re-run: keep as `fetched_failed` and allow retry in future runs within window.

## Acceptance Criteria
- Re-running same day without `--force` skips URLs that were successful earlier and recent.
- URLs that failed earlier within 15 days are retried.
- `--force` re-fetches even recent successful URLs.
- Dedup decisions are visible in `finviz_news.json`.
- Manifest counters reflect dedup and retry behavior accurately.
- No duplicate state corruption in `seen_urls.jsonl` (latest URL state is deterministic).

## Out of Scope
- Multi-ticker orchestration.
- URL canonicalization rules (query cleanup, UTM stripping).
- Database-backed dedup.
