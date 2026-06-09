# finzwiz

Single-ticker CLI that scrapes Finviz, fetches linked news articles, and runs Claude-powered sentiment analysis — producing structured JSON outputs ready for LLM pipelines.

## Setup

```bash
make install          # creates .venv and installs all dependencies
```

Sentiment analysis runs via the **Claude Code CLI** — no separate Anthropic API key required (uses your Claude Code subscription). Make sure `claude` is accessible in your PATH (`which claude` should return a path).

## Commands

### Scrape

Fetches the Finviz quote page and all linked news articles for one ticker:

```bash
PYTHONPATH=src .venv/bin/python -m finzwiz.cli scrape --ticker AAPL
```

| Flag | Default | Description |
|---|---|---|
| `--ticker` | required | Stock ticker, normalized to uppercase |
| `--config` | `config.yaml` | Path to config file |
| `--force` | off | Re-fetch articles even if successfully scraped within the last 15 days |

**Exit codes:** `0` success · `2` bad input/config · `10+` fatal (quote page fetch failed, no articles processed)

### Analyze

Runs Claude sentiment analysis on articles from a scrape run. Only articles not yet analyzed are processed — already-analyzed articles are skipped every time:

```bash
PYTHONPATH=src .venv/bin/python -m finzwiz.cli analyze --ticker AAPL
```

| Flag | Default | Description |
|---|---|---|
| `--ticker` | required | Stock ticker |
| `--config` | `config.yaml` | Path to config file |
| `--date` | today (Pacific) | Analyze a specific past run date, e.g. `2026-06-07` |

**Exit codes:** `0` success · `2` bad input · `10` no scrape data found for that date

### Typical daily workflow

```bash
PYTHONPATH=src .venv/bin/python -m finzwiz.cli scrape --ticker AAPL
PYTHONPATH=src .venv/bin/python -m finzwiz.cli analyze --ticker AAPL
```

## Output files

All files are written under the `data/` directory (configurable via `config.yaml`).

### Per-run outputs (under `data/<TICKER>/<YYYY-MM-DD>/`)

| File | Description |
|---|---|
| `finviz_quote.json` | Parsed Finviz quote page: company info, price, full snapshot table |
| `finviz_news.json` | All news links found on the quote page with dedup status per URL |
| `articles/<ARTICLE_ID>.json` | Extracted article text and metadata; `<ARTICLE_ID>` is `sha256(url)[:24]` |
| `run_manifest.json` | Run stats, artifact paths, and any errors for this run |

### Per-ticker persistent files (under `data/<TICKER>/`)

| File | Description |
|---|---|
| `seen_urls.jsonl` | Dedup log — one record per URL, tracks fetch status and timestamps across runs |
| `sentiment_log.jsonl` | **Growing log** — one record per analyzed article, never overwritten, keyed by `article_id` |
| `sentiment_summary.json` | **Aggregated view** — regenerated each `analyze` run; shows overall and per-date sentiment |

### sentiment_log.jsonl record

Each line is a JSON object:

```json
{
  "article_id": "3f8a1b2c...",
  "ticker": "AAPL",
  "run_date": "2026-06-08",
  "analyzed_at": "2026-06-08T09:14:22-07:00",
  "headline": "Apple announces new chip...",
  "publisher": "Reuters",
  "url": "https://...",
  "sentiment": "bullish",
  "score": 0.75,
  "summary": "Apple's new chip delivers 30% performance gains, signaling strong product cycle ahead.",
  "analysis_error": null
}
```

`score` ranges from `-1.0` (very bearish) to `1.0` (very bullish).

### sentiment_summary.json

Aggregated view rebuilt after every `analyze` run:

```json
{
  "schema_version": "1.0",
  "ticker": "AAPL",
  "generated_at": "2026-06-08T09:15:00-07:00",
  "total_analyzed": 87,
  "overall_sentiment": "bullish",
  "overall_score_avg": 0.42,
  "by_date": [
    {
      "date": "2026-06-08",
      "articles_analyzed": 12,
      "sentiment": "bullish",
      "score_avg": 0.55,
      "top_headlines": [...]
    }
  ]
}
```

`by_date` is sorted newest-first. `top_headlines` contains up to 5 articles with the highest absolute score for that day.

## Automated twice-daily workflow (macOS)

`scripts/workflow.sh` runs the full pipeline — scrape then sentiment analysis — for one or more tickers. It is designed to be called headlessly by the macOS `launchd` scheduler.

### How it works

1. Loops over `$FINZWIZ_TICKERS` (space-separated, default `TSLA`).
2. Runs `finzwiz scrape --ticker <TICKER>` for each ticker.
3. Calls `claude --print "..."` (Claude Code CLI, non-interactive) with a structured prompt. Claude reads the new article files, skips any `article_id` already in `sentiment_log.jsonl`, analyzes sentiment, and writes `sentiment_log.jsonl` + `sentiment_summary.json` directly to disk.
4. Logs everything to `logs/workflow-YYYY-MM-DD.log`.

The analysis step uses the `claude` CLI at `/opt/homebrew/bin/claude` with your existing Claude Code subscription — **no `ANTHROPIC_API_KEY` required**.

### Management commands

```bash
make workflow-install     # register the launchd job (runs at 8 AM + 4 PM local time)
make workflow-uninstall   # remove the launchd job
make workflow-status      # check whether the job is currently registered
make workflow-logs        # tail today's workflow log
make run-workflow         # run the full workflow right now (foreground, for testing)
```

Or use the helper script directly:

```bash
./scripts/manage_workflow.sh install
./scripts/manage_workflow.sh uninstall
./scripts/manage_workflow.sh run
./scripts/manage_workflow.sh status
./scripts/manage_workflow.sh logs
```

### Schedule

The launchd plist (`scripts/com.finzwiz.workflow.plist`) fires at **8:00 AM and 4:00 PM system local time**. It is installed to `~/Library/LaunchAgents/com.finzwiz.workflow.plist`.

If the Mac is asleep at a scheduled time, launchd **will not** run missed jobs automatically — the next scheduled slot will trigger instead. To run a missed execution manually: `make run-workflow`.

### Adding tickers

Edit the `FINZWIZ_TICKERS` value in `scripts/com.finzwiz.workflow.plist`:

```xml
<key>FINZWIZ_TICKERS</key>
<string>TSLA AAPL META MU ENPH HOOD ORCL GOOG MSFT</string>
```

Then reload: `make workflow-install`.

Alternatively, pass the env var for a one-off run:

```bash
FINZWIZ_TICKERS="TSLA NVDA" make run-workflow
```

### Log files

| File | Contents |
|---|---|
| `logs/workflow-YYYY-MM-DD.log` | Timestamped per-run output — scrape results + Claude analysis summary |
| `logs/launchd.log` | Raw stdout/stderr captured by launchd for the scheduled executions |

## Configuration

Key fields in `config.yaml`:

| Field | Default | Description |
|---|---|---|
| `dedup.retention_days` | `15` | Skip re-fetching articles seen successfully within this window |
| `scraping.max_concurrency` | `5` | Parallel article fetch threads |
| `scraping.delay_seconds` | `1` | Per-thread delay before each article fetch |
| `scraping.user_agent` | Chrome UA | Browser UA string sent with every request |
| `articles.max_text_chars` | `0` (no limit) | Truncate extracted article text to this length |
| `sentiment.model` | `claude-haiku-4-5-20251001` | Claude model used for analysis |
| `sentiment.max_articles_per_batch` | `20` | Articles sent per Claude API call |

## Dedup and retry behavior

- Successful articles (fetched within 15 days): **skipped** unless `--force`
- Failed articles (fetched within 15 days): **retried** automatically
- Older than 15 days: always re-fetched
- Sentiment analysis: once an `article_id` appears in `sentiment_log.jsonl` it is **never re-analyzed**, regardless of `--force` or `--date`
