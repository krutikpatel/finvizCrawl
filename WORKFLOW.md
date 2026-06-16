# finzwiz Workflow

This document covers `scripts/workflow.sh` end-to-end: what it does at each phase, how data flows, how sentiment is scored, and how Claude's context is kept small.

---

## Schedule

`scripts/com.finzwiz.workflow.plist` registers a macOS `launchd` agent that fires at **8:00 AM and 4:00 PM** local time.

Missed runs (e.g. Mac asleep) are not retried. Run manually with `make run-workflow`.

### Ticker configuration

Tickers are defined in `config.yaml` as the single source of truth:

```yaml
tickers: "TSLA AAPL META MU ENPH HOOD ORCL GOOG MSFT"
```

`workflow.sh` reads this value automatically — no arguments needed. To add or remove tickers, edit `config.yaml` and the next run picks them up immediately (no plist reload required).

The `FINZWIZ_TICKERS` environment variable overrides `config.yaml` for one-off runs:

```bash
make run-workflow                              # uses config.yaml
FINZWIZ_TICKERS="TSLA NVDA" make run-workflow # override for this run only
```

The plist no longer sets `FINZWIZ_TICKERS` — it has a commented-out placeholder if a permanent override is ever needed.

---

## Pipeline

```
Phase 1+2   Phase 3               Phase 4           Phase 5        Commit / Email
──────────  ────────────────────  ────────────────  ─────────────  ──────────────
Scrape      Single Claude call    Python rebuild    Generate        git commit
Pre-filter  (all tickers, one     sentiment_summary dashboard.html  send email
            session)              per ticker
```

### Phase 1 — Scrape

For each ticker, `finzwiz scrape --ticker <T>` is called. It:

- Fetches the Finviz quote page for `<T>`.
- Finds all linked news URLs, resolves them, deduplicates against `data/<T>/seen_urls.jsonl`.
- Fetches new article pages in parallel (up to `max_concurrency=5` threads), extracts text via trafilatura (primary) or readability-lxml (fallback).
- Writes outputs under `data/<T>/<DATE>/`:
  - `finviz_quote.json` — parsed quote page
  - `finviz_news.json` — all news links with metadata
  - `articles/<ARTICLE_ID>.json` — one file per article; `ARTICLE_ID = sha256(resolved_url)[:24]`
  - `run_manifest.json` — run stats and any errors
- Updates `data/<T>/seen_urls.jsonl` (persistent dedup log across runs).

If the Finviz quote page fetch fails (exit ≥ 10), the ticker is skipped entirely. Scrape results are staged to git immediately after each ticker succeeds.

### Phase 2 — Pre-filter (Python, inline in workflow.sh)

Immediately after a successful scrape, an inline Python script produces `data/<T>/<DATE>/analysis_input.json`. This step is what keeps Claude's context small (see [Context management](#context-management) below).

The script:
1. Reads `data/<T>/sentiment_log.jsonl` → builds a set of all `article_id`s already analyzed.
2. Reads `data/<T>/<DATE>/articles/*.json` → skips any `article_id` already in the set, and skips articles with empty `content.text` (failed fetches).
3. For each new article, looks up `headline`, `publisher`, and `url` from `finviz_news.json`.
4. Truncates article text to **2000 characters**.
5. Writes `analysis_input.json`:

```json
{
  "ticker": "TSLA",
  "run_date": "2026-06-11",
  "articles": [
    {
      "article_id": "3f8a1b2c...",
      "headline": "Tesla announces...",
      "publisher": "Reuters",
      "url": "https://...",
      "text": "...(up to 2000 chars)..."
    }
  ]
}
```

The script prints the count of new articles. If the count is zero (all articles already analyzed), the ticker is excluded from the Claude call entirely.

### Phase 3 — Single Claude analysis call

One `claude --print` session covers **all tickers that have new articles** in a single prompt. This is intentional — each `claude --print` invocation consumes a session against your Claude Code usage limit, so batching all tickers into one call uses one session instead of nine.

The prompt tells Claude to:
1. For each ticker, read its `analysis_input.json`.
2. For each article, assign:
   - **`sentiment`** — `"bullish"`, `"bearish"`, or `"neutral"` based on likely market impact for that specific ticker.
   - **`score`** — float from `-1.0` (very bearish) to `+1.0` (very bullish). Magnitude reflects conviction (e.g. `+0.9` = strong bullish signal, `+0.2` = mildly positive).
   - **`summary`** — one sentence describing the market implication for the ticker (not just what the article says, but what it means for the stock).
3. Append one JSON line per article to `data/<T>/sentiment_log.jsonl`:

```json
{
  "article_id": "3f8a1b2c...",
  "ticker": "TSLA",
  "run_date": "2026-06-11",
  "analyzed_at": "2026-06-11T08:14:22-07:00",
  "headline": "Tesla announces...",
  "publisher": "Reuters",
  "url": "https://...",
  "sentiment": "bullish",
  "score": 0.75,
  "summary": "New chip delivers 30% gains, signaling a strong product cycle.",
  "analysis_error": null
}
```

4. Do **not** write `sentiment_summary.json` — that is Python's job in Phase 4.

Claude processes tickers one by one within the single session. If the session fails mid-batch, whatever was written to `sentiment_log.jsonl` is preserved (append-only log), and Phase 4 still runs to rebuild summaries from what exists.

### Phase 4 — Python summary rebuild

For each ticker that went through Phase 3, `finzwiz rebuild-summary --ticker <T>` reads the **entire** `sentiment_log.jsonl` (all historical records, not just today's) and recomputes `sentiment_summary.json`. This is pure arithmetic — no Claude call needed.

The summary aggregation:
- Groups records by `run_date`.
- Computes `score_avg` per date and `overall_score_avg` across all dates.
- Determines `sentiment` per date (most common label among that day's articles).
- Determines `overall_sentiment` from `overall_score_avg`: `> +0.1` → `"bullish"`, `< -0.1` → `"bearish"`, else `"neutral"`.
- Picks `top_headlines` per date: up to 5 articles sorted by `abs(score)` descending (highest-conviction articles, positive or negative).

Output (`sentiment_summary.json`):

```json
{
  "schema_version": "1.0",
  "ticker": "TSLA",
  "generated_at": "2026-06-11T08:25:00-07:00",
  "total_analyzed": 140,
  "overall_sentiment": "bullish",
  "overall_score_avg": 0.115,
  "sentiment_distribution": {"bullish": 50, "neutral": 70, "bearish": 20},
  "by_date": [
    {
      "date": "2026-06-11",
      "articles_analyzed": 10,
      "sentiment": "bullish",
      "score_avg": 0.22,
      "top_headlines": [...]
    }
  ]
}
```

`by_date` is sorted newest-first. `total_analyzed` and `overall_score_avg` always reflect the full history, not just the current run.

> **Note on `top_headlines`:** the `by_date[].top_headlines` field stores up to **5** articles sorted by `abs(score)` descending (highest-conviction picks). This is used by the email summary. The dashboard reads `sentiment_log.jsonl` directly to get up to **10** headlines per ticker in chronological order (newest `analyzed_at` first), bypassing this cap.

### Phase 5 — Dashboard generation

After all summaries are rebuilt, `scripts/generate_dashboard.py` produces `dashboard.html` — a self-contained, zero-dependency HTML file that opens in any browser.

**Script:** `scripts/generate_dashboard.py --tickers "..." --date YYYY-MM-DD --data-dir data --output dashboard.html`

The file has three sections:

**1. Today's Snapshot** — compact table: ticker, today's sentiment (color-coded), today's score avg, article count.

**2. Score by Day** — one row per ticker showing all-time sentiment + the last 7 dates that appear across any ticker's history. Each date cell is color-coded by that day's sentiment. Missing dates (ticker had no data) show `—`.

**3. Today's Headlines** — one block per ticker, reading directly from `sentiment_log.jsonl` (not from `sentiment_summary.json`):
- Filtered to records where `run_date == today`
- Sorted by `analyzed_at` descending — newest articles first
- Up to **10** per ticker
- Three columns: score (color-coded cell), headline + publisher, one-sentence market implication (`summary` field from the log)

Color scheme: green (`#dcfce7`) = bullish, red (`#fee2e2`) = bearish, grey (`#f3f4f6`) = neutral. Applied to sentiment cells, score cells, and per-ticker headings.

`dashboard.html` is staged and committed alongside the sentiment data on every run where at least one scrape succeeded. It can also be regenerated manually at any time:

```bash
.venv/bin/python scripts/generate_dashboard.py \
  --tickers "TSLA AAPL META MU ENPH HOOD ORCL GOOG MSFT" \
  --date 2026-06-11 \
  --data-dir data \
  --output dashboard.html
```

---

## Context management

### The problem

A naive approach sends all article files to Claude each run. With ~100 articles per ticker at ~25 KB each, that's ~2.5 MB per ticker. Nine tickers = ~23 MB of article data pushed into Claude's context, which exhausts the Claude Code session limit after 1–2 tickers.

### The solution: pre-filter + truncate + batch

Three techniques reduce Claude's context from ~23 MB to ~200–300 KB per run:

| Technique | How | Reduction |
|---|---|---|
| **Skip already-analyzed** | Python checks `article_id` against `sentiment_log.jsonl` before sending anything to Claude. On a second run for the same date, Claude sees zero articles. | ~90% on re-runs |
| **Text truncation** | Article text is capped at **2000 characters** in `analysis_input.json`. Full text is still stored in `articles/*.json` but Claude only sees the excerpt. | ~90% per article |
| **One session for all tickers** | All tickers are batched into a single `claude --print` call instead of one call per ticker. | 9× fewer sessions consumed |

### Why older articles don't need to be re-sent

Each article is scored independently based on its own text. Claude doesn't need to see yesterday's articles to score today's — news articles reference prior events inline when they matter (e.g. "following last week's earnings miss..."). Historical context flows through `sentiment_summary.json` which aggregates all-time scores, not through re-sending old articles to Claude.

### Why the summary is not Claude's job

`sentiment_summary.json` is pure aggregation: grouping by date, averaging scores, counting labels. There is no inference needed. Having Claude regenerate it from the full log would mean sending 100+ historical records per ticker into the context on every run — even when there are no new articles. Python handles this in milliseconds with no context cost.

---

## Data lifecycle

```
(repo root)/
├── dashboard.html               ← regenerated every run by Phase 5; open in browser
└── data/
    └── <TICKER>/
        ├── seen_urls.jsonl          ← persistent dedup log (updated every scrape run)
        ├── sentiment_log.jsonl      ← append-only; one record per analyzed article; never overwritten
        ├── sentiment_summary.json   ← regenerated every run by Python (Phase 4)
        └── <YYYY-MM-DD>/
            ├── finviz_quote.json    ← parsed Finviz quote page
            ├── finviz_news.json     ← all news links with metadata
            ├── run_manifest.json    ← run stats and errors
            ├── analysis_input.json  ← Phase 2 output; compact new-articles-only payload for Claude
            └── articles/
                └── <ARTICLE_ID>.json  ← one per fetched article; full text stored here
```

`sentiment_log.jsonl` is the source of truth for what has been analyzed. An `article_id` in that file is never re-analyzed, regardless of `--force` or re-runs.

---

## Failure handling

| Failure | Effect | Recovery |
|---|---|---|
| Finviz quote page unreachable | Ticker skipped entirely; `run_manifest.json` still written | Re-run after network recovers |
| Article fetch fails (403, timeout) | `articles/<ID>.json` written with `success: false`, `content.text: null`; excluded from `analysis_input.json` | Retried on next run if within `retention_days` |
| Claude session limit hit mid-batch | Tickers already processed are written to `sentiment_log.jsonl`; remaining tickers get no new records | Phase 4 still rebuilds summaries from what exists; next run will analyze the missed articles |
| Claude call fails entirely (exit 1) | `sentiment_log.jsonl` unchanged; Phase 4 still runs | `sentiment_summary.json` reflects previous state; next run retries all unanalyzed articles |
| `rebuild-summary` fails | `sentiment_summary.json` not updated for that ticker | Run `finzwiz rebuild-summary --ticker <T>` manually |
| Dashboard generation fails | `dashboard.html` not updated; prior version remains committed | Run `python scripts/generate_dashboard.py ...` manually |

---

## Configuration knobs

All in `config.yaml`:

| Field | Default | Effect on workflow |
|---|---|---|
| `dedup.retention_days` | `15` | Articles fetched within this window are not re-fetched (unless failed) |
| `scraping.max_concurrency` | `5` | Parallel article fetch threads per ticker |
| `scraping.delay_seconds` | `1` | Per-thread delay before each article fetch (reduces blocking risk) |
| `articles.max_text_chars` | `0` | Truncates stored article text in `articles/*.json`; `0` = no limit. Separate from the 2000-char truncation applied in Phase 2 for Claude |
| `sentiment.log_filename` | `sentiment_log.jsonl` | Name of the append-only analysis log per ticker |
| `sentiment.summary_filename` | `sentiment_summary.json` | Name of the aggregated summary per ticker |

The **2000-character text truncation** in Phase 2 is hardcoded in `workflow.sh` and is independent of `articles.max_text_chars`. It controls only what Claude sees, not what is stored.
