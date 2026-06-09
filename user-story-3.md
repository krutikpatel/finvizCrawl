# User Story 3: Robust News URL Resolution and Fetch Readiness

## Story
As a user, I want every news link from Finviz to be converted into a fetchable absolute URL, so the scraper reduces avoidable failures and captures more article content.

## Goal
Resolve and validate Finviz news URLs before article fetching, especially relative links (for example `/news/...`), while preserving deterministic dedup behavior.

## Scope
- Applies to news links extracted from Finviz quote page.
- Works with current HTTP-only backend.
- Keeps existing dedup rules (exact URL key from Finviz output path) but uses resolved absolute URL for fetching.

## Inputs
- News row URLs from Finviz quote page (`href` values may be absolute or relative).
- Finviz quote page source URL (for URL joining).
- Existing dedup state in `data/<TICKER>/seen_urls.jsonl`.

## Processing Rules
1. For each news link:
2. Build `resolved_url`:
3. If URL is already absolute (`http://` or `https://`), keep as-is.
4. If URL is relative (starts with `/` or lacks scheme), resolve against Finviz origin (`https://finviz.com`).
5. Validate resolved URL scheme is `http` or `https`; otherwise mark as non-fetchable.
6. Use resolved URL for article fetch attempts.
7. Keep output clarity:
8. `finviz_news.json` item should include both original `url` (raw from Finviz) and `resolved_url` (fetch target).
9. Dedup key should be based on `resolved_url` to avoid repeated failures from unresolved forms.

## Required Output Changes
- `finviz_news.json` items gain:
  - `resolved_url`
  - optional `url_resolution_status` (`resolved`, `already_absolute`, `invalid`)
  - optional `url_resolution_reason`
- `articles/<ARTICLE_ID>.json` `source.url` should be the resolved fetch URL.
- `seen_urls.jsonl` `url` should store resolved URL.

## Failure Behavior
- Invalid/unresolvable URLs are non-fatal:
  - record error in manifest,
  - mark corresponding news item resolution status,
  - do not attempt fetch.
- Other article failures remain non-fatal and continue processing.

## Acceptance Criteria
- Relative Finviz links are converted to valid absolute URLs and attempted.
- Manifest no longer reports "Invalid URL ... No scheme supplied" for resolvable relative Finviz links.
- Dedup and retry behavior remains intact across reruns using resolved URLs.
- Existing unit tests stay green, and new tests cover:
  - relative URL resolution
  - absolute URL passthrough
  - invalid URL rejection
  - dedup consistency with resolved URL key

## Out of Scope
- URL canonicalization beyond basic resolution (UTM stripping, query normalization).
- Playwright or JS rendering.
